#!/usr/bin/env python3
"""Rate limit checking for worker pool.

Checks rate limiter before executing requests and re-queues if rate limited.
"""
import time
from typing import Optional, Callable
from queue import PriorityQueue

from infra.llm.models import LLMRequest, LLMEvent
from ..schemas import RequestPhase


def check_rate_limit(
    worker_pool,
    request: LLMRequest,
    queue: PriorityQueue,
    on_event: Optional[Callable]
) -> bool:
    """Check if request can execute now, or needs to wait for rate limit.

    Returns:
        True if request can execute now
        False if rate limited (request has been re-queued)
    """
    if not worker_pool.rate_limiter.can_execute():
        wait_time = worker_pool.rate_limiter.time_until_token()

        # Ensure we wait at least a minimum time to avoid tight loops
        # This handles cases where time_until_token() returns very small values
        min_wait = 0.1  # 100ms minimum
        actual_wait = max(wait_time, min_wait)

        with worker_pool.request_tracking_lock:
            if request.id in worker_pool.active_requests:
                status = worker_pool.active_requests[request.id]
                status.phase = RequestPhase.RATE_LIMITED
                status.phase_entered_at = time.time()
                status.rate_limit_eta = actual_wait

        worker_pool._emit_event(
            on_event,
            LLMEvent.RATE_LIMITED,
            request_id=request.id,
            eta_seconds=actual_wait
        )
        # Sleep full wait_time (no busy-wait loop)
        time.sleep(actual_wait)
        queue.put(request)
        return False

    return True
