#!/usr/bin/env python3
"""
Worker pool for parallel request processing.

Handles:
- Queue-based request management
- Rate limiting coordination
- Worker thread lifecycle
- Result handling (success, retry, failure)
- Request tracking updates
"""

import time
import random
import threading
import sys
import traceback
from queue import PriorityQueue, Empty
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Callable, Dict, Set

from infra.llm.models import (
    LLMRequest, LLMResult, LLMEvent, EventData,
    RequestPhase, RequestStatus, CompletedStatus
)
from infra.llm.rate_limiter import RateLimiter
from .executor import RequestExecutor


class WorkerPool:
    """
    Manages worker threads for parallel LLM request processing.

    Provides:
    - Queue-based architecture with priority support
    - Rate limiting to prevent 429 errors
    - Automatic retry with jitter (failed requests re-enqueue)
    - Request lifecycle tracking
    - Result storage and callbacks

    Thread Safety:
    All state is protected by locks for safe concurrent access from worker threads.

    Lock acquisition order (to prevent deadlocks):
    1. request_tracking_lock (most granular - individual request lifecycle)
    2. results_lock (medium - result storage)
    """

    def __init__(
        self,
        executor: RequestExecutor,
        rate_limiter: RateLimiter,
        max_workers: int,
        retry_jitter: tuple = (1.0, 3.0),
        progress_interval: float = 1.0,
    ):
        """
        Initialize worker pool.

        Args:
            executor: RequestExecutor for processing individual requests
            rate_limiter: RateLimiter for throttling requests
            max_workers: Number of worker threads
            retry_jitter: (min, max) seconds to wait before re-queue
            progress_interval: How often to emit PROGRESS events (seconds)
        """
        self.executor = executor
        self.rate_limiter = rate_limiter
        self.max_workers = max_workers
        self.retry_jitter = retry_jitter
        self.progress_interval = progress_interval

        # Result storage (thread-safe)
        self.results: Dict[str, LLMResult] = {}
        self.results_lock = threading.Lock()

        # Request lifecycle tracking (thread-safe)
        self.request_tracking_lock = threading.Lock()
        self.active_requests: Dict[str, RequestStatus] = {}
        self.recent_completions: Dict[str, CompletedStatus] = {}
        # Calculate TTL cycles from desired TTL (10s) and progress interval
        self.completion_ttl_cycles = int(10.0 / progress_interval)

    def process_batch(
        self,
        requests: list,
        on_event: Optional[Callable[[EventData], None]] = None,
        on_result: Optional[Callable[[LLMResult], None]] = None
    ) -> Dict[str, LLMResult]:
        """
        Process batch of requests using worker pool.

        Args:
            requests: List of LLMRequest objects
            on_event: Callback for lifecycle events
            on_result: Callback for each completed request

        Returns:
            Dict mapping request_id to LLMResult
        """
        if not requests:
            return {}

        # Initialize queue
        queue = PriorityQueue()

        for req in requests:
            req._queued_at = time.time()
            queue.put(req)

            # Track request status
            with self.request_tracking_lock:
                self.active_requests[req.id] = RequestStatus(
                    request_id=req.id,
                    phase=RequestPhase.QUEUED,
                    queued_at=req._queued_at,
                    phase_entered_at=req._queued_at,
                    retry_count=0
                )

            self._emit_event(on_event, LLMEvent.QUEUED, request_id=req.id)

        # Track expected results
        expected_ids = {req.id for req in requests}

        # Process queue with worker pool
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit workers
            futures = []
            for _ in range(min(self.max_workers, len(requests))):
                future = executor.submit(
                    self._worker_loop,
                    queue,
                    on_event,
                    on_result,
                    expected_ids
                )
                futures.append(future)

            # Wait for completion
            for future in futures:
                future.result()

        # Return results in dict form
        with self.results_lock:
            return self.results.copy()

    def _worker_loop(
        self,
        queue: PriorityQueue,
        on_event: Optional[Callable[[EventData], None]],
        on_result: Optional[Callable[[LLMResult], None]],
        expected_ids: Set[str]
    ):
        """
        Worker thread loop - processes requests from queue until empty.

        Args:
            queue: Shared priority queue
            on_event: Event callback
            on_result: Result callback
            expected_ids: Set of expected request IDs (for completion check)
        """
        while True:
            try:
                # Check if all expected results are done
                if self._all_done(expected_ids):
                    break

                # Get next request (non-blocking with timeout)
                request = self._get_next_request(queue, expected_ids)
                if request is None:
                    continue

                # Check rate limiting
                if not self._check_rate_limit(request, queue, on_event):
                    continue  # Re-queued, will retry

                # Consume rate limit token
                self.rate_limiter.consume()

                # Update tracking
                self._update_request_phase(request.id, RequestPhase.DEQUEUED)

                # Execute request
                self._emit_event(on_event, LLMEvent.DEQUEUED, request_id=request.id)
                self._emit_event(on_event, LLMEvent.EXECUTING, request_id=request.id)
                result = self.executor.execute_request(request, on_event)

                # Handle result
                self._handle_result(result, request, queue, on_event, on_result)

            except Exception as e:
                # CRITICAL: Worker thread error
                self._handle_worker_crash(e, request if 'request' in locals() else None, on_event, on_result)
                continue  # Keep worker alive

    def _all_done(self, expected_ids: Set[str]) -> bool:
        """Check if all expected results are complete."""
        with self.results_lock:
            return len(self.results) >= len(expected_ids)

    def _get_next_request(
        self,
        queue: PriorityQueue,
        expected_ids: Set[str]
    ) -> Optional[LLMRequest]:
        """
        Get next request from queue (non-blocking).

        Returns:
            LLMRequest or None if queue empty
        """
        try:
            return queue.get(timeout=0.5)
        except Empty:
            # Double-check we're really done
            if self._all_done(expected_ids):
                return None
            # Still waiting for results
            return None

    def _check_rate_limit(
        self,
        request: LLMRequest,
        queue: PriorityQueue,
        on_event: Optional[Callable]
    ) -> bool:
        """
        Check rate limit, re-queue if needed.

        Returns:
            True if can proceed, False if re-queued
        """
        if not self.rate_limiter.can_execute():
            # Wait for token, then re-queue
            wait_time = self.rate_limiter.time_until_token()

            # Update tracking
            with self.request_tracking_lock:
                if request.id in self.active_requests:
                    status = self.active_requests[request.id]
                    status.phase = RequestPhase.RATE_LIMITED
                    status.phase_entered_at = time.time()
                    status.rate_limit_eta = wait_time

            self._emit_event(
                on_event,
                LLMEvent.RATE_LIMITED,
                request_id=request.id,
                eta_seconds=wait_time
            )
            time.sleep(min(wait_time, 1.0))  # Wait up to 1s, then re-check
            queue.put(request)  # Re-queue
            return False

        return True

    def _update_request_phase(self, request_id: str, phase: RequestPhase):
        """Update request phase tracking."""
        with self.request_tracking_lock:
            if request_id in self.active_requests:
                status = self.active_requests[request_id]
                status.phase = phase
                status.phase_entered_at = time.time()

    def _handle_result(
        self,
        result: LLMResult,
        request: LLMRequest,
        queue: PriorityQueue,
        on_event: Optional[Callable],
        on_result: Optional[Callable]
    ):
        """
        Handle request result (success, retry, or permanent failure).

        Args:
            result: Execution result
            request: Original request
            queue: Queue for re-queueing retries
            on_event: Event callback
            on_result: Result callback
        """
        if result.success:
            self._handle_success(result, request, on_event, on_result)
        elif self.executor.is_retryable(result.error_type):
            self._handle_retry(result, request, queue, on_event)
        else:
            self._handle_permanent_failure(result, request, on_event, on_result)

    def _handle_success(
        self,
        result: LLMResult,
        request: LLMRequest,
        on_event: Optional[Callable],
        on_result: Optional[Callable]
    ):
        """Handle successful request completion."""
        # Move from active to recent completions
        with self.request_tracking_lock:
            if request.id in self.active_requests:
                self.active_requests.pop(request.id)
                self.recent_completions[request.id] = CompletedStatus(
                    request_id=request.id,
                    success=True,
                    total_time_seconds=result.total_time_seconds,
                    execution_time_seconds=result.execution_time_seconds,
                    ttft_seconds=result.ttft_seconds,
                    cost_usd=result.cost_usd,
                    retry_count=request._retry_count,
                    model_used=result.model_used,
                    cycles_remaining=self.completion_ttl_cycles
                )

        self._emit_event(on_event, LLMEvent.COMPLETED, request_id=request.id)
        self._store_result(result)
        if on_result:
            on_result(result)

    def _handle_retry(
        self,
        result: LLMResult,
        request: LLMRequest,
        queue: PriorityQueue,
        on_event: Optional[Callable]
    ):
        """Handle retryable failure - re-queue request."""
        # Check if we have fallback models available
        router = getattr(request, '_router', None)
        has_fallback = router and router.has_fallback()

        if has_fallback:
            # Try next fallback model
            next_model = router.next_model()
            request._retry_count += 1
            jitter = random.uniform(*self.retry_jitter)
            time.sleep(jitter)
            queue.put(request)

            import logging
            logger = logging.getLogger(__name__)
            logger.info(
                f"Falling back to {next_model} for {request.id}",
                extra={
                    'request_id': request.id,
                    'previous_model': router.models[router.current_index - 1],
                    'fallback_model': next_model,
                    'retry_count': request._retry_count,
                    'error': result.error_message
                }
            )
        else:
            # Re-queue with same model (standard retry)
            request._retry_count += 1
            jitter = random.uniform(*self.retry_jitter)
            time.sleep(jitter)
            queue.put(request)

        # Update tracking
        with self.request_tracking_lock:
            if request.id in self.active_requests:
                status = self.active_requests[request.id]
                status.phase = RequestPhase.QUEUED
                status.phase_entered_at = time.time()
                status.retry_count = request._retry_count

                # Add to recent completions temporarily (so progress shows the failure)
                self.recent_completions[request.id] = CompletedStatus(
                    request_id=request.id,
                    success=False,
                    total_time_seconds=result.total_time_seconds,
                    execution_time_seconds=result.execution_time_seconds,
                    error_message=result.error_message,
                    cost_usd=result.cost_usd,
                    retry_count=request._retry_count,
                    model_used=result.model_used,
                    cycles_remaining=self.completion_ttl_cycles
                )

        self._emit_event(
            on_event,
            LLMEvent.RETRY_QUEUED,
            request_id=request.id,
            retry_count=request._retry_count,
            queue_position=queue.qsize()
        )

    def _handle_permanent_failure(
        self,
        result: LLMResult,
        request: LLMRequest,
        on_event: Optional[Callable],
        on_result: Optional[Callable]
    ):
        """Handle permanent failure (non-retryable error type)."""
        # Move from active to recent completions
        with self.request_tracking_lock:
            if request.id in self.active_requests:
                self.active_requests.pop(request.id)
                self.recent_completions[request.id] = CompletedStatus(
                    request_id=request.id,
                    success=False,
                    total_time_seconds=result.total_time_seconds,
                    execution_time_seconds=result.execution_time_seconds,
                    error_message=result.error_message,
                    retry_count=request._retry_count,
                    model_used=result.model_used,
                    cycles_remaining=self.completion_ttl_cycles
                )

        self._emit_event(on_event, LLMEvent.FAILED, request_id=request.id)
        self._store_result(result)
        if on_result:
            on_result(result)

    def _handle_worker_crash(
        self,
        error: Exception,
        request: Optional[LLMRequest],
        on_event: Optional[Callable],
        on_result: Optional[Callable]
    ):
        """Handle critical worker thread crash."""
        error_detail = traceback.format_exc()

        # Create failure result so batch doesn't hang
        if request and hasattr(request, 'id'):
            failure_result = LLMResult(
                request_id=request.id,
                success=False,
                error_type="worker_exception",
                error_message=f"Worker thread exception: {type(error).__name__}: {str(error)}",
                request=request
            )

            self._store_result(failure_result)

            try:
                self._emit_event(on_event, LLMEvent.FAILED, request_id=request.id)
            except Exception:
                pass  # Don't propagate emit errors

            if on_result:
                try:
                    on_result(failure_result)
                except Exception:
                    pass

        # Log to stderr (visible even with console_output=False)
        error_msg = (
            f"❌ CRITICAL: Worker thread crashed with unexpected error:\n"
            f"   Error: {error}\n"
            f"   Type: {type(error).__name__}\n"
        )
        if request and hasattr(request, 'id'):
            error_msg += f"   Request ID: {request.id}\n"
        error_msg += f"   Full traceback:\n{error_detail}"

        print(error_msg, file=sys.stderr, flush=True)

    def _store_result(self, result: LLMResult):
        """Thread-safe result storage."""
        with self.results_lock:
            self.results[result.request_id] = result

    def _emit_event(
        self,
        callback: Optional[Callable[[EventData], None]],
        event_type: LLMEvent,
        request_id: Optional[str] = None,
        **kwargs
    ):
        """Emit event if callback provided."""
        if not callback:
            return

        event = EventData(
            event_type=event_type,
            request_id=request_id,
            timestamp=time.time(),
            **kwargs
        )
        callback(event)

    def get_active_requests(self) -> Dict[str, RequestStatus]:
        """Get all currently active requests."""
        with self.request_tracking_lock:
            return {
                req_id: RequestStatus(
                    request_id=status.request_id,
                    phase=status.phase,
                    queued_at=status.queued_at,
                    phase_entered_at=status.phase_entered_at,
                    retry_count=status.retry_count,
                    rate_limit_eta=status.rate_limit_eta
                )
                for req_id, status in self.active_requests.items()
            }

    def get_recent_completions(self) -> Dict[str, CompletedStatus]:
        """Get recently completed/failed requests (within TTL window)."""
        with self.request_tracking_lock:
            return {
                req_id: CompletedStatus(
                    request_id=comp.request_id,
                    success=comp.success,
                    total_time_seconds=comp.total_time_seconds,
                    execution_time_seconds=comp.execution_time_seconds,
                    ttft_seconds=comp.ttft_seconds,
                    cost_usd=comp.cost_usd,
                    error_message=comp.error_message,
                    retry_count=comp.retry_count,
                    model_used=comp.model_used,
                    cycles_remaining=comp.cycles_remaining
                )
                for req_id, comp in self.recent_completions.items()
            }

    def expire_old_completions(self):
        """Expire old completions (called periodically from progress events)."""
        with self.request_tracking_lock:
            expired = []
            for req_id, comp in self.recent_completions.items():
                comp.cycles_remaining -= 1
                if comp.cycles_remaining <= 0:
                    expired.append(req_id)

            for req_id in expired:
                del self.recent_completions[req_id]
