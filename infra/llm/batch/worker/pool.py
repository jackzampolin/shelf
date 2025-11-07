#!/usr/bin/env python3
"""Worker pool for parallel LLM request execution.

The WorkerPool orchestrates parallel execution of LLM requests:
- Queues requests with priority ordering
- Spawns worker threads to process queue
- Enforces rate limits
- Handles retries and errors
- Tracks request lifecycle phases
"""
import logging
import time
import threading
from queue import PriorityQueue
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Callable, Dict, Set

from infra.llm.models import LLMRequest, LLMResult, LLMEvent, EventData
from ..schemas import RequestPhase, RequestStatus
from infra.llm.rate_limiter import RateLimiter
from ..executor import RequestExecutor

from . import handlers, queue, rate_limit, tracking

logger = logging.getLogger(__name__)


class WorkerPool:
    def __init__(
        self,
        executor: RequestExecutor,
        rate_limiter: RateLimiter,
        max_workers: int,
        logger=None,
        retry_jitter: tuple = (1.0, 3.0),
        progress_interval: float = 1.0,
    ):
        if logger is None:
            raise ValueError("WorkerPool requires a logger instance")
        self.executor = executor
        self.rate_limiter = rate_limiter
        self.max_workers = max_workers
        self.logger = logger
        self.retry_jitter = retry_jitter
        self.progress_interval = progress_interval

        self.results: Dict[str, LLMResult] = {}
        self.results_lock = threading.Lock()

        self.request_tracking_lock = threading.Lock()
        self.active_requests: Dict[str, RequestStatus] = {}

        self.watchdog_lock = threading.Lock()
        self.last_watchdog_log = 0.0

    def process_batch(
        self,
        requests: list,
        on_event: Optional[Callable[[EventData], None]] = None,
        on_result: Optional[Callable[[LLMResult], None]] = None
    ) -> Dict[str, LLMResult]:
        """Process a batch of LLM requests in parallel.

        Args:
            requests: List of LLMRequest objects to process
            on_event: Optional callback for lifecycle events (QUEUED, EXECUTING, COMPLETED, etc.)
            on_result: Optional callback for each completed result (success or failure)

        Returns:
            Dict mapping request_id to LLMResult
        """
        if not requests:
            return {}

        request_queue = PriorityQueue()

        for req in requests:
            req._queued_at = time.time()
            request_queue.put(req)

            with self.request_tracking_lock:
                self.active_requests[req.id] = RequestStatus(
                    request_id=req.id,
                    phase=RequestPhase.QUEUED,
                    queued_at=req._queued_at,
                    phase_entered_at=req._queued_at,
                    retry_count=0
                )

            self._emit_event(on_event, LLMEvent.QUEUED, request_id=req.id)

        expected_ids = {req.id for req in requests}

        # Log initial queue state for debugging
        self.logger.info(
                f"Queued {len(requests)} requests for processing",
                total_requests=len(requests),
                request_ids_sample=sorted(list(expected_ids))[:5] + ['...'] if len(expected_ids) > 5 else sorted(list(expected_ids))
            )

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = []
            for _ in range(min(self.max_workers, len(requests))):
                future = executor.submit(
                    self._worker_loop,
                    request_queue,
                    on_event,
                    on_result,
                    expected_ids
                )
                futures.append(future)

            for future in futures:
                future.result()

        # Check for missing results after workers finish
        with self.results_lock:
            completed_ids = set(self.results.keys())
            missing_ids = expected_ids - completed_ids

            if missing_ids:
                self.logger.debug(
                    f"CRITICAL: {len(missing_ids)} requests never completed",
                    missing_request_ids=sorted(list(missing_ids))[:20],
                    total_expected=len(expected_ids),
                    total_completed=len(completed_ids)
                )

            return self.results.copy()

    def _worker_loop(
        self,
        request_queue: PriorityQueue,
        on_event: Optional[Callable[[EventData], None]],
        on_result: Optional[Callable[[LLMResult], None]],
        expected_ids: Set[str]
    ):
        """Main loop for worker thread - dequeue and execute requests until done."""
        worker_id = threading.current_thread().name
        self.logger.debug(f"Worker {worker_id} started")

        consecutive_empty_gets = 0
        last_watchdog_check = time.time()
        watchdog_interval = 30.0  # Check every 30 seconds

        while True:
            try:
                if self._all_done(expected_ids):
                    self.logger.debug(f"Worker {worker_id} exiting (all done)")
                    break

                request = self._get_next_request(request_queue, expected_ids)
                if request is None:
                    consecutive_empty_gets += 1

                    # Watchdog: Check if we're stuck waiting for missing requests
                    # Only one worker logs every 60 seconds to avoid spam
                    now = time.time()
                    if now - last_watchdog_check >= watchdog_interval:
                        should_log = False
                        with self.watchdog_lock:
                            if now - self.last_watchdog_log >= 60.0:  # Only log once per minute
                                self.last_watchdog_log = now
                                should_log = True

                        if should_log:
                            with self.results_lock:
                                completed_count = len(self.results)
                                expected_count = len(expected_ids)

                                if completed_count < expected_count:
                                    missing_count = expected_count - completed_count
                                    completed_ids = set(self.results.keys())
                                    missing_ids = expected_ids - completed_ids

                                    self.logger.debug(
                                            f"WATCHDOG: Stuck waiting for {missing_count} missing requests",
                                            completed=completed_count,
                                            expected=expected_count,
                                            missing_request_ids=sorted(list(missing_ids))[:10]
                                        )

                        last_watchdog_check = now

                    continue
                else:
                    consecutive_empty_gets = 0  # Reset counter when we get a request

                if not self._check_rate_limit(request, request_queue, on_event):
                    continue

                self.rate_limiter.consume()
                self.logger.debug(f"Worker {worker_id} executing {request.id}")

                self._update_request_phase(request.id, RequestPhase.DEQUEUED)

                self._emit_event(on_event, LLMEvent.DEQUEUED, request_id=request.id)
                self._emit_event(on_event, LLMEvent.EXECUTING, request_id=request.id)
                result = self.executor.execute_request(request, on_event)

                self.logger.debug(f"Worker {worker_id} RECEIVED RESULT: {request.id} (success={result.success})")

                if result.success:
                    self.logger.debug(f"Worker {worker_id} ✓ {request.id} ({result.execution_time_seconds:.1f}s)")
                else:
                    self.logger.debug(
                        f"Worker {worker_id} ✗ {request.id} ({result.execution_time_seconds:.1f}s)",
                        error_type=result.error_type,
                        error=result.error_message
                    )

                self._handle_result(result, request, request_queue, on_event, on_result)

            except Exception as e:
                self._handle_worker_crash(e, request if 'request' in locals() else None, on_event, on_result)
                continue  # Keep worker alive

    # Delegation methods - these call helper modules

    def _all_done(self, expected_ids: Set[str]) -> bool:
        """Check if all expected requests completed - delegates to queue module."""
        return queue.check_if_all_done(self, expected_ids)

    def _get_next_request(self, request_queue: PriorityQueue, expected_ids: Set[str]) -> Optional[LLMRequest]:
        """Get next request from queue - delegates to queue module."""
        return queue.get_next_request(self, request_queue, expected_ids)

    def _check_rate_limit(self, request: LLMRequest, request_queue: PriorityQueue, on_event: Optional[Callable]) -> bool:
        """Check rate limit before executing - delegates to rate_limit module."""
        return rate_limit.check_rate_limit(self, request, request_queue, on_event)

    def _update_request_phase(self, request_id: str, phase: RequestPhase):
        """Update request phase - delegates to tracking module."""
        tracking.update_request_phase(self, request_id, phase)

    def get_active_requests(self) -> Dict[str, RequestStatus]:
        """Get snapshot of active requests - delegates to tracking module."""
        return tracking.get_active_requests(self)

    def _handle_result(
        self,
        result: LLMResult,
        request: LLMRequest,
        request_queue: PriorityQueue,
        on_event: Optional[Callable],
        on_result: Optional[Callable]
    ):
        """Route result to appropriate handler - delegates to handlers module."""
        self.logger.debug(f"Worker HANDLING RESULT: {request.id} (success={result.success})")

        if result.success:
            self._handle_success(result, request, on_event, on_result)
        elif self.executor.is_retryable(result.error_type):
            self._handle_retry(result, request, request_queue, on_event)
        else:
            self._handle_permanent_failure(result, request, on_event, on_result)

    def _handle_success(self, result: LLMResult, request: LLMRequest, on_event: Optional[Callable], on_result: Optional[Callable]):
        """Handle successful request - delegates to handlers module."""
        handlers.handle_success(self, result, request, on_event, on_result)

    def _handle_retry(self, result: LLMResult, request: LLMRequest, request_queue: PriorityQueue, on_event: Optional[Callable]):
        """Handle retryable failure - delegates to handlers module."""
        handlers.handle_retry(self, result, request, request_queue, on_event)

    def _handle_permanent_failure(self, result: LLMResult, request: LLMRequest, on_event: Optional[Callable], on_result: Optional[Callable]):
        """Handle permanent failure - delegates to handlers module."""
        handlers.handle_permanent_failure(self, result, request, on_event, on_result)

    def _handle_worker_crash(self, error: Exception, request: Optional[LLMRequest], on_event: Optional[Callable], on_result: Optional[Callable]):
        """Handle worker thread crash - delegates to handlers module."""
        handlers.handle_worker_crash(self, error, request, on_event, on_result)

    # Core infrastructure methods (stay in pool.py)

    def _store_result(self, result: LLMResult):
        """Store completed result - thread-safe."""
        with self.results_lock:
            self.results[result.request_id] = result

    def _emit_event(
        self,
        callback: Optional[Callable[[EventData], None]],
        event_type: LLMEvent,
        request_id: Optional[str] = None,
        **kwargs
    ):
        """Emit lifecycle event to callback if provided."""
        if not callback:
            return

        event = EventData(
            event_type=event_type,
            request_id=request_id,
            timestamp=time.time(),
            **kwargs
        )
        callback(event)
