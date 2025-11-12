from typing import Optional, Set
from queue import PriorityQueue, Empty

from infra.llm.models import LLMRequest

def get_next_request(
    worker_pool,
    queue: PriorityQueue,
    expected_ids: Set[str]
) -> Optional[LLMRequest]:
    try:
        return queue.get(timeout=0.5)
    except Empty:
        if check_if_all_done(worker_pool, expected_ids):
            return None
        return None


def check_if_all_done(worker_pool, expected_ids: Set[str]) -> bool:
    with worker_pool.results_lock:
        return len(worker_pool.results) >= len(expected_ids)
