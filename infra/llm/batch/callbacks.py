#!/usr/bin/env python3
import time
from typing import Callable, Optional

from infra.llm.models import LLMResult, LLMEvent, EventData
from .stats import BatchStatsTracker


def wrap_with_stats_tracking(
    original_callback: Optional[Callable[[LLMResult], None]],
    stats_tracker: BatchStatsTracker
) -> Callable[[LLMResult], None]:
    """Wrap result callback to track stats."""
    def wrapped(result: LLMResult):
        if result.success:
            stats_tracker.record_success(
                cost_usd=result.cost_usd,
                usage=result.usage
            )
        else:
            stats_tracker.record_failure()

        if original_callback:
            original_callback(result)

    return wrapped


def wrap_with_progress_monitoring(
    original_callback: Optional[Callable[[EventData], None]],
    stats_tracker: BatchStatsTracker,
    worker_pool: 'WorkerPool',
    rate_limiter: 'RateLimiter',
    total_requests: int,
    progress_interval: float
) -> Callable[[EventData], None]:
    """Wrap event callback to emit periodic progress events and track retries."""
    last_progress_time = [time.time()]

    def wrapped(event: EventData):
        # Track retry events in stats
        if event.event_type == LLMEvent.RETRY_QUEUED:
            stats_tracker.record_retry()

        now = time.time()
        if now - last_progress_time[0] >= progress_interval:
            emit_progress_event(
                original_callback,
                stats_tracker,
                worker_pool,
                rate_limiter,
                total_requests
            )
            last_progress_time[0] = now

        if original_callback:
            original_callback(event)

    return wrapped


def emit_progress_event(
    callback: Optional[Callable[[EventData], None]],
    stats_tracker: BatchStatsTracker,
    worker_pool: 'WorkerPool',
    rate_limiter: 'RateLimiter',
    total_requests: int
):
    """Emit batch-level progress event."""
    if not callback:
        return

    stats = stats_tracker.get_stats()
    completed = len(worker_pool.results)
    in_progress = len(worker_pool.get_active_requests())
    queued = total_requests - completed - in_progress

    event = EventData(
        event_type=LLMEvent.PROGRESS,
        timestamp=time.time(),
        completed=completed,
        failed=stats['requests_failed'],
        in_flight=in_progress,
        queued=max(0, queued),
        total_cost_usd=stats['total_cost_usd'],
        rate_limit_status=rate_limiter.get_status()
    )
    callback(event)
