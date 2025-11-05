#!/usr/bin/env python3
"""
Batch LLM client - main orchestrator.

Wires together:
- HTTP session management
- Statistics tracking
- Streaming execution
- Request execution
- Worker pool
- Progress monitoring

Provides high-level API for batch processing with retries, rate limiting,
and comprehensive telemetry.
"""

import time
from pathlib import Path
from typing import List, Optional, Callable
from datetime import datetime

from infra.llm.models import LLMRequest, LLMResult, LLMEvent, EventData
from infra.llm.client import LLMClient
from infra.llm.rate_limiter import RateLimiter
from infra.config import Config

from .http_session import ThreadLocalSessionManager
from .stats import BatchStatsTracker, BatchStats
from .streaming import StreamingExecutor
from .executor import RequestExecutor
from .worker import WorkerPool


class LLMBatchClient:
    """
    Batch client for parallel LLM request processing.

    Features:
    - Queue-based architecture with priority support
    - Rate limiting to prevent 429 errors
    - Automatic retry with jitter (failed requests re-enqueue)
    - Event-driven progress tracking
    - Defensive cost tracking
    - Thread-safe for concurrent execution

    Thread Safety:
    -------------
    This class is thread-safe for concurrent execution across worker threads.

    Usage:
        client = LLMBatchClient(
            max_workers=10,
            rate_limit=60,
            max_retries=5
        )

        results = client.process_batch(
            requests,
            on_event=event_handler,
            on_result=result_handler
        )
    """

    def __init__(
        self,
        max_workers: Optional[int] = None,
        rate_limit: Optional[int] = None,
        max_retries: int = 5,
        retry_jitter: tuple = (1.0, 3.0),
        verbose: bool = False,
        progress_interval: float = 1.0,
        log_dir: Optional[Path] = None,
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
            log_timestamp: Optional timestamp string for log filenames
        """
        # Use Config defaults if not specified
        self.max_workers = max_workers if max_workers is not None else Config.max_workers
        self.rate_limit = rate_limit if rate_limit is not None else Config.rate_limit_requests_per_minute
        self.max_retries = max_retries
        self.retry_jitter = retry_jitter
        self.verbose = verbose
        self.progress_interval = progress_interval
        self.log_dir = log_dir

        # Set up logging
        if self.log_dir:
            self.log_dir = Path(self.log_dir)
            self.log_dir.mkdir(parents=True, exist_ok=True)

            # Generate timestamp if not provided
            if not log_timestamp:
                log_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            self.log_timestamp = log_timestamp

        # Create core components
        self.llm_client = LLMClient()
        self.rate_limiter = RateLimiter(requests_per_minute=self.rate_limit)
        self.session_manager = ThreadLocalSessionManager()

        # Create processing pipeline
        self.streaming_executor = StreamingExecutor(
            llm_client=self.llm_client,
            session_manager=self.session_manager,
            verbose=self.verbose
        )

        self.request_executor = RequestExecutor(
            streaming_executor=self.streaming_executor,
            max_retries=self.max_retries
        )

        self.worker_pool = WorkerPool(
            executor=self.request_executor,
            rate_limiter=self.rate_limiter,
            max_workers=self.max_workers,
            retry_jitter=self.retry_jitter,
            progress_interval=self.progress_interval,
            log_dir=self.log_dir
        )

        # Initialize stats tracker
        self.stats_tracker: Optional[BatchStatsTracker] = None
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

        # Initialize stats tracker
        self.batch_start_time = time.time()
        self.stats_tracker = BatchStatsTracker(batch_start_time=self.batch_start_time)

        # Wrap callbacks to track stats
        wrapped_on_result = self._create_stats_tracking_callback(on_result)

        # Wrap event callback for progress monitoring
        wrapped_on_event = self._create_progress_monitoring_callback(
            on_event, len(requests)
        )

        # Process batch via worker pool
        results_dict = self.worker_pool.process_batch(
            requests,
            on_event=wrapped_on_event,
            on_result=wrapped_on_result
        )

        # Return results in original order
        result_list = []
        for req in requests:
            result = results_dict.get(req.id)
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

    def _create_stats_tracking_callback(
        self,
        original_callback: Optional[Callable[[LLMResult], None]]
    ) -> Callable[[LLMResult], None]:
        """
        Wrap result callback to track stats.

        Args:
            original_callback: User's result callback

        Returns:
            Wrapped callback that tracks stats
        """
        def wrapped_callback(result: LLMResult):
            # Track in stats
            if result.success:
                self.stats_tracker.record_success(
                    cost_usd=result.cost_usd,
                    usage=result.usage
                )
            else:
                self.stats_tracker.record_failure()

            # Call original callback
            if original_callback:
                original_callback(result)

        return wrapped_callback

    def _create_progress_monitoring_callback(
        self,
        original_callback: Optional[Callable[[EventData], None]],
        total_requests: int
    ) -> Callable[[EventData], None]:
        """
        Wrap event callback to emit progress events.

        Args:
            original_callback: User's event callback
            total_requests: Total request count

        Returns:
            Wrapped callback that emits progress
        """
        last_progress_time = [time.time()]  # Use list for mutable reference

        def wrapped_callback(event: EventData):
            # Emit periodic progress events
            now = time.time()
            if now - last_progress_time[0] >= self.progress_interval:
                self._emit_progress_event(original_callback, total_requests)
                last_progress_time[0] = now

                # Expire old completions
                self.worker_pool.expire_old_completions()

            # Call original callback
            if original_callback:
                original_callback(event)

        return wrapped_callback

    def _emit_progress_event(
        self,
        callback: Optional[Callable[[EventData], None]],
        total_requests: int
    ):
        """Emit batch-level progress event."""
        if not callback:
            return

        stats = self.stats_tracker.get_stats()
        completed = len(self.worker_pool.results)
        in_progress = len(self.worker_pool.get_active_requests())
        queued = total_requests - completed - in_progress

        event = EventData(
            event_type=LLMEvent.PROGRESS,
            timestamp=time.time(),
            completed=completed,
            failed=stats['requests_failed'],
            in_flight=in_progress,
            queued=max(0, queued),
            total_cost_usd=stats['total_cost_usd'],
            rate_limit_status=self.rate_limiter.get_status()
        )
        callback(event)

    def get_batch_stats(self, total_requests: int = None) -> BatchStats:
        """
        Calculate aggregate batch statistics.

        Args:
            total_requests: Total request count (optional, for queued calc)

        Returns:
            BatchStats with aggregated metrics
        """
        if not self.stats_tracker:
            # No batch has been processed yet
            return BatchStats(
                total_requests=0,
                completed=0,
                failed=0,
                in_progress=0,
                queued=0,
                avg_time_per_request=0.0,
                min_time=0.0,
                max_time=0.0,
                total_cost_usd=0.0,
                avg_cost_per_request=0.0,
                total_prompt_tokens=0,
                total_tokens=0,
                total_reasoning_tokens=0,
                avg_tokens_per_request=0.0,
                requests_per_second=0.0,
                rate_limit_utilization=0.0,
                rate_limit_tokens_available=0
            )

        return self.stats_tracker.get_batch_stats(
            total_requests=total_requests or len(self.worker_pool.results),
            completed_results=self.worker_pool.results,
            in_progress_count=len(self.worker_pool.get_active_requests()),
            rate_limit_status=self.rate_limiter.get_status()
        )

    def get_stats(self) -> dict:
        """Get current aggregate statistics."""
        if not self.stats_tracker:
            return {
                'requests_completed': 0,
                'requests_failed': 0,
                'total_cost_usd': 0.0,
                'total_prompt_tokens': 0,
                'total_tokens': 0,
                'total_reasoning_tokens': 0,
                'retry_count': 0,
                'rate_limit_status': self.rate_limiter.get_status()
            }

        stats = self.stats_tracker.get_stats()
        stats['rate_limit_status'] = self.rate_limiter.get_status()
        return stats

    def get_rate_limit_status(self) -> dict:
        """Get current rate limit consumption."""
        return self.rate_limiter.get_status()

    def get_active_requests(self) -> dict:
        """Get all currently active requests."""
        return self.worker_pool.get_active_requests()

    def get_recent_completions(self) -> dict:
        """Get recently completed/failed requests."""
        return self.worker_pool.get_recent_completions()
