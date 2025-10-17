#!/usr/bin/env python3
"""
Batch LLM client with queue-based retries and comprehensive telemetry.

Provides request-based interface for processing batches of LLM calls with:
- Rate limiting (token bucket algorithm)
- Queue-based retry (failed requests re-enqueue with jitter)
- Event-driven progress tracking
- Defensive cost tracking
- Per-request telemetry
"""

import time
import json
import random
import threading
from queue import PriorityQueue, Empty
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional, Callable, Tuple

from infra.llm_models import LLMRequest, LLMResult, EventData, LLMEvent
from infra.rate_limiter import RateLimiter
from infra.llm_client import LLMClient


class LLMBatchClient:
    """
    Batch client for parallel LLM request processing.

    Features:
    - Queue-based architecture with priority support
    - Rate limiting to prevent 429 errors
    - Automatic retry with jitter (failed requests re-enqueue)
    - Event-driven progress tracking
    - Defensive cost tracking (internal + callback)
    - Thread-safe for concurrent execution
    """

    def __init__(
        self,
        max_workers: int = 30,
        rate_limit: int = 150,  # requests per minute
        max_retries: int = 5,
        retry_jitter: Tuple[float, float] = (1.0, 3.0),
        json_retry_budget: int = 2,
        verbose: bool = False,
        progress_interval: float = 1.0,
    ):
        """
        Initialize batch client.

        Args:
            max_workers: Thread pool size
            rate_limit: Max requests per minute
            max_retries: Max attempts per request (failed requests re-queue)
            retry_jitter: (min, max) seconds to wait before re-queue
            json_retry_budget: Separate retry budget for JSON parse errors
            verbose: Enable per-request progress events
            progress_interval: How often to emit PROGRESS events (seconds)
        """
        self.max_workers = max_workers
        self.rate_limit = rate_limit
        self.max_retries = max_retries
        self.retry_jitter = retry_jitter
        self.json_retry_budget = json_retry_budget
        self.verbose = verbose
        self.progress_interval = progress_interval

        # Core components
        self.rate_limiter = RateLimiter(requests_per_minute=rate_limit)
        self.llm_client = LLMClient()

        # State tracking
        self.stats_lock = threading.Lock()
        self.stats = {
            'total_cost_usd': 0.0,
            'total_tokens': 0,
            'requests_completed': 0,
            'requests_failed': 0,
            'retry_count': 0,
        }

        # Result storage (thread-safe)
        self.results: Dict[str, LLMResult] = {}
        self.results_lock = threading.Lock()

    def process_batch(
        self,
        requests: List[LLMRequest],
        json_parser: Optional[Callable] = None,
        on_event: Optional[Callable[[EventData], None]] = None,
        on_result: Optional[Callable[[LLMResult], None]] = None,
    ) -> List[LLMResult]:
        """
        Process batch of requests with queue-based retry.

        Args:
            requests: List of LLMRequest objects
            json_parser: Optional parser for structured outputs
            on_event: Callback for lifecycle events
            on_result: Callback for each completed request

        Returns:
            List of LLMResult in same order as input requests
        """
        if not requests:
            return []

        # Initialize queue
        queue = PriorityQueue()
        for req in requests:
            req._queued_at = time.time()
            queue.put(req)
            self._emit_event(on_event, LLMEvent.QUEUED, request_id=req.id)

        # Track expected results
        expected_ids = {req.id for req in requests}
        total_requests = len(requests)

        # Process queue with worker pool
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit initial workers
            futures = []
            for _ in range(min(self.max_workers, len(requests))):
                future = executor.submit(
                    self._worker_loop,
                    queue,
                    json_parser,
                    on_event,
                    on_result,
                    expected_ids
                )
                futures.append(future)

            # Emit initial progress immediately (shows workers starting)
            self._emit_progress_event(on_event, total_requests)

            # Monitor progress
            last_progress_time = time.time()
            while any(not f.done() for f in futures):
                time.sleep(0.1)

                # Emit periodic progress events
                now = time.time()
                if now - last_progress_time >= self.progress_interval:
                    self._emit_progress_event(on_event, total_requests)
                    last_progress_time = now

            # Final progress event
            self._emit_progress_event(on_event, total_requests)

        # Return results in original order
        result_list = []
        for req in requests:
            with self.results_lock:
                result = self.results.get(req.id)
                if result:
                    result_list.append(result)
                else:
                    # Should not happen, but create failure result if missing
                    result_list.append(LLMResult(
                        request_id=req.id,
                        success=False,
                        error_type="missing",
                        error_message="Result not found after processing",
                        request=req
                    ))

        return result_list

    def _worker_loop(
        self,
        queue: PriorityQueue,
        json_parser: Optional[Callable],
        on_event: Optional[Callable[[EventData], None]],
        on_result: Optional[Callable[[LLMResult], None]],
        expected_ids: set
    ):
        """Worker thread loop - processes requests from queue until empty."""
        while True:
            try:
                # Check if all expected results are done
                with self.results_lock:
                    results_count = len(self.results)
                    expected_count = len(expected_ids)
                    if results_count >= expected_count:
                        break

                # Get next request (non-blocking with timeout)
                try:
                    request = queue.get(timeout=0.5)
                except Empty:
                    # Check if we're really done (no in-flight work)
                    with self.results_lock:
                        if len(self.results) >= len(expected_ids):
                            break
                    continue

                # Rate limiting
                if not self.rate_limiter.can_execute():
                    # Wait for token, then re-queue
                    wait_time = self.rate_limiter.time_until_token()
                    self._emit_event(
                        on_event,
                        LLMEvent.RATE_LIMITED,
                        request_id=request.id,
                        eta_seconds=wait_time
                    )
                    time.sleep(min(wait_time, 1.0))  # Wait up to 1s, then re-check
                    queue.put(request)  # Re-queue
                    continue

                # Consume rate limit token
                self.rate_limiter.consume()

                # Process request
                self._emit_event(on_event, LLMEvent.DEQUEUED, request_id=request.id)
                result = self._execute_request(request, json_parser, on_event)

                # Handle result
                if result.success:
                    # Success - store and callback
                    self._emit_event(on_event, LLMEvent.COMPLETED, request_id=request.id)
                    self._store_result(result)
                    if on_result:
                        on_result(result)

                    with self.stats_lock:
                        self.stats['requests_completed'] += 1
                        self.stats['total_cost_usd'] += result.cost_usd
                        self.stats['total_tokens'] += result.usage.get('completion_tokens', 0)

                else:
                    # Failure - check if retryable
                    if request._retry_count < self.max_retries and self._is_retryable(result.error_type):
                        # Re-queue with jitter
                        request._retry_count += 1
                        jitter = random.uniform(*self.retry_jitter)
                        time.sleep(jitter)
                        queue.put(request)

                        self._emit_event(
                            on_event,
                            LLMEvent.RETRY_QUEUED,
                            request_id=request.id,
                            retry_count=request._retry_count,
                            queue_position=queue.qsize()
                        )

                        with self.stats_lock:
                            self.stats['retry_count'] += 1
                    else:
                        # Permanent failure
                        self._emit_event(on_event, LLMEvent.FAILED, request_id=request.id)
                        self._store_result(result)
                        if on_result:
                            on_result(result)

                        with self.stats_lock:
                            self.stats['requests_failed'] += 1

            except Exception as e:
                # CRITICAL: Worker thread error - this should almost never happen
                import traceback
                import sys
                error_detail = traceback.format_exc()

                # Create a failure result for the request so batch doesn't hang forever
                if 'request' in locals() and hasattr(request, 'id'):
                    failure_result = LLMResult(
                        request_id=request.id,
                        success=False,
                        error_type="worker_exception",
                        error_message=f"Worker thread exception: {type(e).__name__}: {str(e)}",
                        request=request
                    )

                    # Store the failure result so batch doesn't wait forever
                    self._store_result(failure_result)

                    # Try to emit FAILED event
                    try:
                        self._emit_event(on_event, LLMEvent.FAILED, request_id=request.id)
                    except Exception as emit_error:
                        # Log emit failure but don't propagate - we've already stored the result
                        pass

                    with self.stats_lock:
                        self.stats['requests_failed'] += 1

                # Log error to stderr so it's visible even with console_output=False
                error_msg = (
                    f"❌ CRITICAL: Worker thread crashed with unexpected error:\n"
                    f"   Error: {e}\n"
                    f"   Type: {type(e).__name__}\n"
                )
                if 'request' in locals() and hasattr(request, 'id'):
                    error_msg += f"   Request ID: {request.id}\n"
                error_msg += f"   Full traceback:\n{error_detail}"

                print(error_msg, file=sys.stderr, flush=True)

                # Continue to keep worker alive, but this indicates a serious bug
                continue

    def _execute_request(
        self,
        request: LLMRequest,
        json_parser: Optional[Callable],
        on_event: Optional[Callable[[EventData], None]]
    ) -> LLMResult:
        """Execute single LLM request with telemetry."""
        start_time = time.time()
        queue_time = start_time - request._queued_at

        self._emit_event(on_event, LLMEvent.EXECUTING, request_id=request.id)

        try:
            # Build provider config if specified
            if request.provider_order or request.provider_sort:
                # OpenRouter provider routing via response_format isn't standard
                # For now, we'll skip provider routing in minimal version
                # TODO: Add provider routing support
                pass

            # Use existing LLMClient
            if json_parser:
                # Use JSON retry wrapper
                response, usage, cost = self.llm_client.call_with_json_retry(
                    model=request.model,
                    messages=request.messages,
                    json_parser=json_parser,
                    temperature=request.temperature,
                    max_retries=self.json_retry_budget,
                    max_tokens=request.max_tokens,
                    timeout=request.timeout,
                    images=request.images,
                    response_format=request.response_format
                )
                parsed_json = response  # call_with_json_retry returns parsed JSON
                response_text = json.dumps(response)
            else:
                # Standard call
                response_text, usage, cost = self.llm_client.call(
                    model=request.model,
                    messages=request.messages,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    timeout=request.timeout,
                    images=request.images,
                    response_format=request.response_format
                )
                parsed_json = None

            # Build success result
            execution_time = time.time() - start_time
            return LLMResult(
                request_id=request.id,
                success=True,
                response=response_text,
                parsed_json=parsed_json,
                attempts=request._retry_count + 1,
                total_time_seconds=execution_time + queue_time,
                queue_time_seconds=queue_time,
                execution_time_seconds=execution_time,
                tokens_received=usage.get('completion_tokens', 0),
                usage=usage,
                cost_usd=cost,
                request=request
            )

        except json.JSONDecodeError as e:
            # JSON parsing failed after retries
            execution_time = time.time() - start_time
            return LLMResult(
                request_id=request.id,
                success=False,
                error_type="json_parse",
                error_message=f"JSON parsing failed: {str(e)}",
                attempts=request._retry_count + 1,
                total_time_seconds=execution_time + queue_time,
                queue_time_seconds=queue_time,
                execution_time_seconds=execution_time,
                request=request
            )

        except Exception as e:
            # Other errors (timeout, HTTP, etc.)
            execution_time = time.time() - start_time
            error_type = self._classify_error(e)

            return LLMResult(
                request_id=request.id,
                success=False,
                error_type=error_type,
                error_message=str(e),
                attempts=request._retry_count + 1,
                total_time_seconds=execution_time + queue_time,
                queue_time_seconds=queue_time,
                execution_time_seconds=execution_time,
                request=request
            )

    def _classify_error(self, error: Exception) -> str:
        """Classify error type for retry logic."""
        error_str = str(error).lower()
        if 'timeout' in error_str:
            return 'timeout'
        elif '5' in error_str and ('server' in error_str or 'error' in error_str):
            return '5xx'
        elif '429' in error_str:
            return '429_rate_limit'
        elif '4' in error_str and ('client' in error_str or 'error' in error_str):
            return '4xx'
        else:
            return 'unknown'

    def _is_retryable(self, error_type: Optional[str]) -> bool:
        """Check if error type is retryable."""
        retryable = ['timeout', '5xx', '429_rate_limit', 'unknown']
        return error_type in retryable

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

        # Only emit per-request events if verbose mode
        if request_id and not self.verbose and event_type != LLMEvent.FAILED:
            return

        event = EventData(
            event_type=event_type,
            request_id=request_id,
            timestamp=time.time(),
            **kwargs
        )
        callback(event)

    def _emit_progress_event(
        self,
        callback: Optional[Callable[[EventData], None]],
        total_requests: int
    ):
        """Emit batch-level progress event."""
        if not callback:
            return

        with self.stats_lock:
            stats = self.stats.copy()

        with self.results_lock:
            completed = len(self.results)

        event = EventData(
            event_type=LLMEvent.PROGRESS,
            timestamp=time.time(),
            completed=completed,
            failed=stats['requests_failed'],
            in_flight=self.max_workers,  # Approximate
            queued=total_requests - completed,
            total_cost_usd=stats['total_cost_usd'],
            rate_limit_status=self.rate_limiter.get_status()
        )
        callback(event)

    def get_stats(self) -> Dict:
        """Get aggregate statistics."""
        with self.stats_lock:
            stats = self.stats.copy()

        rate_limit_status = self.rate_limiter.get_status()

        return {
            **stats,
            'rate_limit_status': rate_limit_status,
        }

    def get_rate_limit_status(self) -> Dict:
        """Get current rate limit consumption."""
        return self.rate_limiter.get_status()


if __name__ == "__main__":
    # Simple test (requires API key)
    print("Testing LLMBatchClient...")
    print("(Skipping - requires real API calls)")
    print("See correction stage for integration test")
