#!/usr/bin/env python3
import time
from queue import PriorityQueue

from infra.llm.models import LLMRequest
from ..schemas import RequestPhase

def check_rate_limit(
    worker_pool,
    request: LLMRequest,
    queue: PriorityQueue
) -> bool:
    if not worker_pool.rate_limiter.can_execute():
        wait_time = worker_pool.rate_limiter.time_until_token()

        min_wait = 0.1  # 100ms minimum
        actual_wait = max(wait_time, min_wait)

        with worker_pool.request_tracking_lock:
            if request.id in worker_pool.active_requests:
                status = worker_pool.active_requests[request.id]
                status.phase = RequestPhase.RATE_LIMITED
                status.phase_entered_at = time.time()
                status.rate_limit_eta = actual_wait

        time.sleep(actual_wait)
        queue.put(request)
        return False

    return True
