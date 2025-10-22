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

from infra.llm.models import (
    LLMRequest, LLMResult, EventData, LLMEvent,
    RequestPhase, RequestStatus, CompletedStatus, BatchStats
)
from infra.llm.rate_limiter import RateLimiter
from infra.llm.client import LLMClient, CHARS_PER_TOKEN_ESTIMATE
from infra.config import Config


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
        max_workers: Optional[int] = None,
        rate_limit: Optional[int] = None,
        max_retries: int = 5,
        retry_jitter: Tuple[float, float] = (1.0, 3.0),
        verbose: bool = False,
        progress_interval: float = 1.0,
        log_dir: Optional['Path'] = None,
        log_timestamp: Optional[str] = None,
    ):
        """
        Initialize batch client.

        Args:
            max_workers: Thread pool size (default: Config.max_workers)
            rate_limit: Max requests per minute (default: Config.rate_limit_requests_per_minute)
            max_retries: Max attempts per request (failed requests re-queue)
            retry_jitter: (min, max) seconds to wait before re-queue
            verbose: Enable per-request progress events
            progress_interval: How often to emit PROGRESS events (seconds)
            log_dir: Optional directory to log failed LLM calls
            log_timestamp: Optional timestamp string for log filenames (e.g., "20250101_120530")
        """
        # Use Config defaults if not specified
        self.max_workers = max_workers if max_workers is not None else Config.max_workers
        self.rate_limit = rate_limit if rate_limit is not None else Config.rate_limit_requests_per_minute
        self.max_retries = max_retries
        self.retry_jitter = retry_jitter
        self.verbose = verbose
        self.progress_interval = progress_interval
        self.log_dir = log_dir
        self.log_timestamp = log_timestamp

        # Set up failure logging if log_dir provided
        if self.log_dir:
            from pathlib import Path
            from datetime import datetime
            self.log_dir = Path(self.log_dir)
            self.log_dir.mkdir(parents=True, exist_ok=True)

            # Generate timestamp if not provided
            if not self.log_timestamp:
                self.log_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

            self.failure_log_path = self.log_dir / f"llm_failures_{self.log_timestamp}.jsonl"
            self.retry_log_path = self.log_dir / f"llm_retries_{self.log_timestamp}.jsonl"

        # Core components
        self.rate_limiter = RateLimiter(requests_per_minute=rate_limit)
        self.llm_client = LLMClient()

        # State tracking
        self.stats_lock = threading.Lock()
        self.stats = {
            'total_cost_usd': 0.0,
            'total_tokens': 0,
            'total_reasoning_tokens': 0,  # Track reasoning tokens separately (for supported models)
            'requests_completed': 0,
            'requests_failed': 0,
            'retry_count': 0,
        }

        # Result storage (thread-safe)
        self.results: Dict[str, LLMResult] = {}
        self.results_lock = threading.Lock()

        # Request lifecycle tracking (thread-safe)
        self.request_tracking_lock = threading.Lock()
        self.active_requests: Dict[str, RequestStatus] = {}
        self.recent_completions: Dict[str, CompletedStatus] = {}
        # Calculate TTL cycles from desired TTL (10s) and progress interval
        self.completion_ttl_cycles = int(10.0 / self.progress_interval)
        self.batch_start_time: Optional[float] = None

    def process_batch(
        self,
        requests: List[LLMRequest],
        on_event: Optional[Callable[[EventData], None]] = None,
        on_result: Optional[Callable[[LLMResult], None]] = None,
    ) -> List[LLMResult]:
        """
        Process batch of requests with queue-based retry.

        All requests must have response_format set for structured JSON output.
        All requests are streamed for full telemetry (TTFT, tokens/sec, progress).

        Args:
            requests: List of LLMRequest objects (must have response_format)
            on_event: Callback for lifecycle events
            on_result: Callback for each completed request

        Returns:
            List of LLMResult in same order as input requests

        Raises:
            ValueError: If any request is missing response_format
        """
        if not requests:
            return []

        # Validate all requests have response_format
        for req in requests:
            if not req.response_format:
                raise ValueError(
                    f"Request {req.id} missing response_format. "
                    "All requests must use structured JSON output."
                )

        # Initialize queue
        queue = PriorityQueue()
        self.batch_start_time = time.time()  # Track batch start

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
        total_requests = len(requests)

        # Process queue with worker pool
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit initial workers
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
                    continue

                # Consume rate limit token
                self.rate_limiter.consume()

                # Update tracking
                with self.request_tracking_lock:
                    if request.id in self.active_requests:
                        status = self.active_requests[request.id]
                        status.phase = RequestPhase.DEQUEUED
                        status.phase_entered_at = time.time()

                # Process request
                self._emit_event(on_event, LLMEvent.DEQUEUED, request_id=request.id)
                result = self._execute_request(request, on_event)

                # Handle result
                if result.success:
                    # Success - move from active to recent completions
                    with self.request_tracking_lock:
                        if request.id in self.active_requests:
                            status = self.active_requests.pop(request.id)
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

                    with self.stats_lock:
                        self.stats['requests_completed'] += 1
                        self.stats['total_cost_usd'] += result.cost_usd
                        self.stats['total_tokens'] += result.usage.get('completion_tokens', 0)
                        self.stats['total_reasoning_tokens'] += result.usage.get('reasoning_tokens', 0)

                else:
                    # Failure - check for fallback or retry
                    if self._is_retryable(result.error_type):
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

                            # Log fallback attempt
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
                                # This will be removed when request succeeds or becomes permanent failure
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

                        # Log retry attempt for debugging transient failures
                        self._log_retry(result, request._retry_count)

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
                        # Permanent failure - move from active to recent completions
                        with self.request_tracking_lock:
                            if request.id in self.active_requests:
                                status = self.active_requests.pop(request.id)
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

                        # Log failure to disk if configured
                        self._log_failure(result)

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
        on_event: Optional[Callable[[EventData], None]]
    ) -> LLMResult:
        """
        Execute single LLM request with telemetry.

        All requests are streamed for full telemetry (TTFT, tokens/sec, progress).
        All requests must have response_format for structured JSON output.

        Manages:
        - Model fallback routing via ModelRouter
        - Error classification and retry logic
        - Comprehensive telemetry (queue time, execution time, TTFT, cost)
        - Request phase tracking for observability
        """
        start_time = time.time()
        queue_time = start_time - request._queued_at

        # Update tracking
        with self.request_tracking_lock:
            if request.id in self.active_requests:
                status = self.active_requests[request.id]
                status.phase = RequestPhase.EXECUTING
                status.phase_entered_at = start_time

        self._emit_event(on_event, LLMEvent.EXECUTING, request_id=request.id)

        try:
            # Initialize router if fallback models configured
            if not hasattr(request, '_router') or request._router is None:
                if request.fallback_models:
                    from infra.llm.router import ModelRouter
                    request._router = ModelRouter(
                        primary_model=request.model,
                        fallback_models=request.fallback_models
                    )

            # Get current model from router (or use request.model if no router)
            current_model = request._router.get_current() if request._router else request.model

            # Stream the request (always)
            response_text, usage, cost, ttft = self._execute_with_streaming_events(
                request, current_model, on_event, start_time
            )

            # Parse structured JSON response (OpenRouter guarantees valid JSON)
            parsed_json = json.loads(response_text)

            # Mark success in router if present
            if request._router:
                request._router.mark_success()

            # Build success result
            execution_time = time.time() - start_time

            # Calculate tokens per second
            tokens_per_second = 0.0
            completion_tokens = usage.get('completion_tokens', 0)
            if execution_time > 0 and completion_tokens > 0:
                tokens_per_second = completion_tokens / execution_time

            # Extract provider from model name (e.g., "anthropic/claude-sonnet-4" → "anthropic")
            provider = None
            if '/' in current_model:
                provider = current_model.split('/')[0]

            return LLMResult(
                request_id=request.id,
                success=True,
                response=response_text,
                parsed_json=parsed_json,
                attempts=request._retry_count + 1,
                total_time_seconds=execution_time + queue_time,
                queue_time_seconds=queue_time,
                execution_time_seconds=execution_time,
                ttft_seconds=ttft,
                tokens_received=completion_tokens,
                tokens_per_second=tokens_per_second,
                usage=usage,
                cost_usd=cost,
                provider=provider,
                model_used=current_model,
                models_attempted=request._router.get_models_attempted() if request._router else [request.model],
                request=request
            )

        except json.JSONDecodeError as e:
            # JSON parsing failed - this should never happen with structured responses
            # Log the malformed response for debugging
            import logging
            logger = logging.getLogger(__name__)

            # Truncate response for logging (first/last 500 chars)
            response_preview = response_text
            if len(response_text) > 1000:
                response_preview = f"{response_text[:500]}...{response_text[-500:]}"

            logger.warning(
                f"Structured JSON parsing failed for {request.id}",
                extra={
                    'request_id': request.id,
                    'model': current_model,
                    'error': str(e),
                    'response_length': len(response_text),
                    'response_preview': response_preview,
                    'response_format': request.response_format
                }
            )

            execution_time = time.time() - start_time
            return LLMResult(
                request_id=request.id,
                success=False,
                error_type="json_parse",
                error_message=f"Structured JSON parsing failed: {str(e)}",
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
        """
        Classify error type for retry logic and error handling.

        Error types (in priority order):
        - 'timeout': Network timeouts (retryable)
        - '5xx': Server errors 500-599 (retryable)
        - '429_rate_limit': Rate limiting (retryable with backoff)
        - '413_payload_too_large': Payload too large (retryable - may succeed on retry)
        - '422_unprocessable': Unprocessable entity (retryable - often transient deserialization issues)
        - '4xx': Other client errors 400-499 (non-retryable)
        - 'unknown': Unclassified errors (retryable to be safe)

        Args:
            error: Exception raised during LLM request

        Returns:
            String error type for use in retry logic
        """
        error_str = str(error).lower()
        if 'timeout' in error_str:
            return 'timeout'
        elif '5' in error_str and ('server' in error_str or 'error' in error_str):
            return '5xx'
        elif '429' in error_str:
            return '429_rate_limit'
        elif '413' in error_str:
            return '413_payload_too_large'
        elif '422' in error_str:
            return '422_unprocessable'
        elif '4' in error_str and ('client' in error_str or 'error' in error_str):
            return '4xx'
        else:
            return 'unknown'

    def _is_retryable(self, error_type: Optional[str]) -> bool:
        """Check if error type is retryable.

        Retryable errors (retry indefinitely):
        - timeout: Network timeouts
        - 5xx: Server errors (transient)
        - 429_rate_limit: Rate limiting (will retry after wait)
        - 413_payload_too_large: Payload too large (retry - may succeed on different attempt)
        - 422_unprocessable: Provider deserialization issues (transient)
        - json_parse: JSON parsing failures (fallback models may generate valid JSON)
        - unknown: Unclassified errors (retry to be safe)

        Non-retryable errors:
        - 4xx: Client errors (bad request, auth, forbidden, etc.)
        """
        retryable = ['timeout', '5xx', '429_rate_limit', '413_payload_too_large', '422_unprocessable', 'json_parse', 'unknown']
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
        """Emit batch-level progress event with TTL expiration."""
        if not callback:
            return

        with self.stats_lock:
            stats = self.stats.copy()

        with self.results_lock:
            completed = len(self.results)

        # Calculate batch stats
        batch_stats = self.get_batch_stats(total_requests)

        # Expire old completions
        with self.request_tracking_lock:
            expired = []
            for req_id, comp in self.recent_completions.items():
                comp.cycles_remaining -= 1
                if comp.cycles_remaining <= 0:
                    expired.append(req_id)

            for req_id in expired:
                del self.recent_completions[req_id]

        event = EventData(
            event_type=LLMEvent.PROGRESS,
            timestamp=time.time(),
            completed=completed,
            failed=stats['requests_failed'],
            in_flight=batch_stats.in_progress,
            queued=batch_stats.queued,
            total_cost_usd=stats['total_cost_usd'],
            rate_limit_status=self.rate_limiter.get_status()
        )
        callback(event)

    def _emit_streaming_event(
        self,
        on_event: Optional[Callable[[EventData], None]],
        request: 'LLMRequest',
        streaming_state: Dict,
        start_time: float,
        is_final: bool = False
    ):
        """
        Emit a single streaming progress event.

        Args:
            on_event: Event callback
            request: Current request
            streaming_state: Streaming state dict
            start_time: Request start time
            is_final: True if this is the final event (ETA = 0)
        """
        if not on_event:
            return

        # Only emit if verbose mode OR final event
        if not self.verbose and not is_final:
            return

        tokens = streaming_state['tokens_so_far']
        elapsed = time.time() - start_time

        # Calculate rate and ETA (defensive against division by zero)
        if elapsed < 0.01:
            tokens_per_second = 0.0
        else:
            tokens_per_second = tokens / elapsed

        # Estimate total output tokens based on OCR input size
        # Data analysis: corrected output is 73% of OCR input (±11% stdev)
        ocr_tokens = request.metadata.get('ocr_tokens') if request.metadata else None
        if ocr_tokens and ocr_tokens > 0:
            estimated_total = int(ocr_tokens * 0.73)
        else:
            # Fallback if OCR tokens not available (median from analysis)
            estimated_total = request.max_tokens or 1200
        remaining_tokens = max(0, estimated_total - tokens)

        if tokens_per_second > 0:
            eta_seconds = remaining_tokens / tokens_per_second
        else:
            eta_seconds = None

        # Final event should show ETA = 0
        if is_final:
            eta_seconds = 0.0

        # Build display message (pre-formatted for progress bar)
        page_id = request.id.replace('page_', 'p')
        if eta_seconds is not None:
            message = f"{page_id}: {tokens} tokens, {tokens_per_second:.0f} tok/s, ETA {eta_seconds:.1f}s"
        else:
            message = f"{page_id}: {tokens} tokens, {tokens_per_second:.0f} tok/s"

        # Extract stage from request metadata (if present)
        stage = request.metadata.get('stage') if request.metadata else None

        self._emit_event(
            on_event,
            LLMEvent.STREAMING,
            request_id=request.id,
            tokens_received=tokens,
            tokens_per_second=tokens_per_second,
            eta_seconds=eta_seconds,
            retry_count=request._retry_count,
            stage=stage,
            message=message
        )

    def _execute_with_streaming_events(
        self,
        request: 'LLMRequest',
        model: str,
        on_event: Optional[Callable[[EventData], None]],
        start_time: float
    ) -> Tuple[str, Dict, float]:
        """
        Execute streaming LLM call with throttled event emission.

        Emits STREAMING events during token generation, showing:
        - tokens_received (estimated count during streaming)
        - tokens_per_second (generation rate)
        - eta_seconds (estimated time to completion)

        Args:
            request: LLM request to execute
            model: Model to use (from router if fallback active)
            on_event: Event callback (if None, no events emitted)
            start_time: Request start timestamp (for elapsed calculation)

        Returns:
            Tuple of (response_text, usage_dict, cost_usd, ttft_seconds)
        """
        import requests as req_lib

        # Build API request (similar to LLMClient.call)
        headers = {
            "Authorization": f"Bearer {self.llm_client.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": model,
            "messages": request.messages,
            "temperature": request.temperature,
            "stream": True  # Enable streaming
        }

        if request.max_tokens:
            payload["max_tokens"] = request.max_tokens

        if request.response_format:
            payload["response_format"] = request.response_format

        # Add images if present (multimodal)
        if request.images:
            messages_with_images = self.llm_client._add_images_to_messages(
                request.messages, request.images
            )
            payload["messages"] = messages_with_images

        # Make streaming request
        response = None
        try:
            response = req_lib.post(
                self.llm_client.base_url,
                headers=headers,
                json=payload,
                stream=True,
                timeout=request.timeout
            )
            response.raise_for_status()

            # Streaming state (thread-local - no locks needed)
            # Estimate input tokens for ETA calculation (chars / 3 ≈ tokens)
            input_chars = sum(len(str(m.get('content', ''))) for m in request.messages)
            input_tokens = input_chars // 3

            streaming_state = {
                'start_time': start_time,
                'last_emit': start_time,
                'tokens_so_far': 0,
                'full_content': [],
                'actual_usage': None,  # Will be populated from final chunk
                'parse_errors': 0,  # Track malformed SSE chunks
                'input_tokens': input_tokens,  # For ETA calculation
                'first_token_time': None,  # Track time to first token
                'first_token_emitted': False  # Ensure we emit FIRST_TOKEN event only once
            }

            # Throttle interval (seconds between events)
            # Reduced to 0.2s for more frequent updates during streaming
            throttle_interval = 0.2

            # Parse SSE stream
            for line in response.iter_lines():
                if not line:
                    continue

                line = line.decode('utf-8')
                if line.startswith('data: '):
                    data_str = line[6:]

                    if data_str == '[DONE]':
                        break

                    try:
                        chunk = json.loads(data_str)

                        # Check for usage data in final chunk
                        if 'usage' in chunk:
                            usage_data = chunk['usage']

                            # Validate usage structure before using
                            if (isinstance(usage_data, dict) and
                                'prompt_tokens' in usage_data and
                                'completion_tokens' in usage_data):
                                streaming_state['actual_usage'] = usage_data
                            else:
                                # Malformed usage data - log warning
                                import logging
                                logger = logging.getLogger(__name__)
                                logger.warning(
                                    f"Malformed usage data in SSE chunk for {request.id}",
                                    extra={
                                        'request_id': request.id,
                                        'usage_data': usage_data,
                                        'expected_keys': ['prompt_tokens', 'completion_tokens']
                                    }
                                )

                        # Extract content delta
                        if 'choices' in chunk and len(chunk['choices']) > 0:
                            delta = chunk['choices'][0].get('delta', {})
                            content = delta.get('content', '')

                            if content:
                                # Track time to first token
                                if streaming_state['first_token_time'] is None:
                                    streaming_state['first_token_time'] = time.time()
                                    ttft = streaming_state['first_token_time'] - start_time

                                    # Emit FIRST_TOKEN event (once)
                                    if not streaming_state['first_token_emitted']:
                                        page_id = request.id.replace('page_', 'p')
                                        self._emit_event(
                                            on_event,
                                            LLMEvent.FIRST_TOKEN,
                                            request_id=request.id,
                                            eta_seconds=ttft,  # Reuse field for TTFT
                                            message=f"{page_id}: Streaming started (TTFT: {ttft:.2f}s)"
                                        )
                                        streaming_state['first_token_emitted'] = True

                                streaming_state['full_content'].append(content)

                                # Estimate tokens from character count
                                total_chars = len(''.join(streaming_state['full_content']))
                                streaming_state['tokens_so_far'] = total_chars // CHARS_PER_TOKEN_ESTIMATE

                                # Emit throttled STREAMING event
                                now = time.time()
                                if now - streaming_state['last_emit'] >= throttle_interval:
                                    self._emit_streaming_event(
                                        on_event, request, streaming_state, start_time
                                    )
                                    streaming_state['last_emit'] = now

                    except json.JSONDecodeError as e:
                        # Track parse errors - a few dropped chunks are acceptable
                        streaming_state['parse_errors'] += 1

                        # Log first error for debugging
                        if streaming_state['parse_errors'] == 1:
                            import logging
                            logger = logging.getLogger(__name__)
                            logger.warning(
                                f"SSE chunk parse error for {request.id}",
                                extra={
                                    'request_id': request.id,
                                    'chunk_preview': data_str[:200],
                                    'error': str(e)
                                }
                            )

                        # If too many parse errors, stream may be corrupted
                        if streaming_state['parse_errors'] > 10:
                            raise ValueError(
                                f"Too many SSE parse errors ({streaming_state['parse_errors']}) "
                                f"for request {request.id} - stream may be corrupted"
                            )

                        continue

            # Emit final streaming event (show complete state)
            if on_event and streaming_state['tokens_so_far'] > 0:
                self._emit_streaming_event(
                    on_event, request, streaming_state, start_time, is_final=True
                )

            # Build final response
            complete_response = ''.join(streaming_state['full_content'])

            # Use actual usage if available, otherwise estimate
            if streaming_state['actual_usage']:
                usage = streaming_state['actual_usage']
            else:
                # Fallback to char-based estimate
                prompt_chars = sum(len(m.get('content', '')) for m in request.messages)
                completion_chars = len(complete_response)

                usage = {
                    'prompt_tokens': prompt_chars // CHARS_PER_TOKEN_ESTIMATE,
                    'completion_tokens': completion_chars // CHARS_PER_TOKEN_ESTIMATE,
                    '_estimated': True  # Flag that this is an estimate
                }

                # Log warning that we're using estimates (affects cost accuracy)
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(
                    f"No usage data in SSE stream for request {request.id}, using estimate. "
                    f"Cost tracking may be inaccurate.",
                    extra={
                        'request_id': request.id,
                        'model': model,
                        'estimated_tokens': usage
                    }
                )

            # Calculate cost (use model parameter, not request.model)
            cost = self.llm_client.cost_calculator.calculate_cost(
                model,
                usage['prompt_tokens'],
                usage['completion_tokens'],
                num_images=len(request.images) if request.images else 0
            )

            # Calculate TTFT if first token was received
            ttft = None
            if streaming_state['first_token_time'] is not None:
                ttft = streaming_state['first_token_time'] - start_time

            return complete_response, usage, cost, ttft

        finally:
            # Ensure HTTP response is always closed to prevent resource leaks
            if response is not None:
                response.close()

    def get_active_requests(self) -> Dict[str, RequestStatus]:
        """
        Get all currently active requests (non-terminal states).

        Returns:
            Dict mapping request_id to RequestStatus
        """
        with self.request_tracking_lock:
            # Return copy to avoid external mutation
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
        """
        Get recently completed/failed requests (within TTL window).

        Returns:
            Dict mapping request_id to CompletedStatus
        """
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

    def get_request_status(self, request_id: str) -> Optional[RequestStatus]:
        """
        Get status for a specific request (if still tracked).

        Args:
            request_id: Request ID to query

        Returns:
            RequestStatus if active, None if completed/expired
        """
        with self.request_tracking_lock:
            if request_id in self.active_requests:
                status = self.active_requests[request_id]
                return RequestStatus(
                    request_id=status.request_id,
                    phase=status.phase,
                    queued_at=status.queued_at,
                    phase_entered_at=status.phase_entered_at,
                    retry_count=status.retry_count,
                    rate_limit_eta=status.rate_limit_eta
                )
            return None

    def get_batch_stats(self, total_requests: int = None) -> BatchStats:
        """
        Calculate aggregate batch statistics.

        Args:
            total_requests: Total request count (optional, for queued calc)

        Returns:
            BatchStats with aggregated metrics
        """
        with self.stats_lock:
            stats = self.stats.copy()

        with self.results_lock:
            completed_count = len(self.results)

            # Calculate timing stats from results
            if self.results:
                times = [r.total_time_seconds for r in self.results.values()]
                avg_time = sum(times) / len(times)
                min_time = min(times)
                max_time = max(times)
            else:
                avg_time = min_time = max_time = 0.0

            # Calculate cost stats
            if completed_count > 0:
                avg_cost = stats['total_cost_usd'] / completed_count
            else:
                avg_cost = 0.0

        with self.request_tracking_lock:
            in_progress = len(self.active_requests)

        # Calculate throughput
        if self.batch_start_time:
            elapsed = time.time() - self.batch_start_time
            requests_per_second = completed_count / elapsed if elapsed > 0 else 0.0
        else:
            requests_per_second = 0.0

        # Get rate limit status
        rate_status = self.rate_limiter.get_status()

        # Calculate queued count
        if total_requests:
            queued = total_requests - completed_count - in_progress
        else:
            queued = 0

        return BatchStats(
            total_requests=total_requests or (completed_count + in_progress),
            completed=completed_count,
            failed=stats['requests_failed'],
            in_progress=in_progress,
            queued=max(0, queued),
            avg_time_per_request=avg_time,
            min_time=min_time,
            max_time=max_time,
            total_cost_usd=stats['total_cost_usd'],
            avg_cost_per_request=avg_cost,
            requests_per_second=requests_per_second,
            rate_limit_utilization=rate_status.get('utilization', 0.0),
            rate_limit_tokens_available=rate_status.get('tokens_available', 0)
        )

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

    def _log_retry(self, result: LLMResult, retry_count: int):
        """
        Log retryable LLM failure to {log_dir}/llm_retries.jsonl.

        This logs transient failures (413, 422, 5xx) that will be retried.
        Helps debug issues like rate limits, payload size, etc.

        Args:
            result: Failed LLMResult being retried
            retry_count: Current retry attempt number
        """
        if not self.log_dir:
            return

        try:
            import datetime

            # Extract JSON-serializable metadata only
            metadata = result.request.metadata if result.request else None
            serializable_metadata = {}
            if metadata:
                for key, value in metadata.items():
                    try:
                        json.dumps(value)
                        serializable_metadata[key] = value
                    except (TypeError, ValueError):
                        serializable_metadata[key] = f"<non-serializable: {type(value).__name__}>"

            log_entry = {
                'timestamp': datetime.datetime.now().isoformat(),
                'request_id': result.request_id,
                'retry_count': retry_count,
                'error_type': result.error_type,
                'error_message': result.error_message,
                'execution_time_seconds': result.execution_time_seconds,
                'model': result.request.model if result.request else None,
                'metadata': serializable_metadata
            }

            # Append to JSONL file (separate from permanent failures)
            with open(self.retry_log_path, 'a') as f:
                f.write(json.dumps(log_entry) + '\n')

        except Exception:
            # Don't let logging errors crash the pipeline
            pass

    def _log_failure(self, result: LLMResult):
        """
        Log permanently failed LLM request to {log_dir}/llm_failures.jsonl.

        Args:
            result: Failed LLMResult to log (after all retries exhausted)
        """
        if not self.log_dir:
            return

        try:
            import datetime

            # Extract JSON-serializable metadata only
            # (metadata may contain objects like BookStorage that aren't serializable)
            metadata = result.request.metadata if result.request else None
            serializable_metadata = {}
            if metadata:
                for key, value in metadata.items():
                    try:
                        # Test if value is JSON serializable
                        json.dumps(value)
                        serializable_metadata[key] = value
                    except (TypeError, ValueError):
                        # Skip non-serializable values (e.g., BookStorage objects)
                        serializable_metadata[key] = f"<non-serializable: {type(value).__name__}>"

            log_entry = {
                'timestamp': datetime.datetime.now().isoformat(),
                'request_id': result.request_id,
                'error_type': result.error_type,
                'error_message': result.error_message,
                'attempts': result.attempts,
                'model': result.request.model if result.request else None,
                'metadata': serializable_metadata
            }

            # Append to JSONL file (thread-safe with 'a' mode)
            with open(self.failure_log_path, 'a') as f:
                f.write(json.dumps(log_entry) + '\n')

        except Exception:
            # Don't let logging errors crash the pipeline
            # Silently fail - logging is nice-to-have, not critical
            pass


if __name__ == "__main__":
    # Simple test (requires API key)
    print("Testing LLMBatchClient...")
    print("(Skipping - requires real API calls)")
    print("See correction stage for integration test")
