#!/usr/bin/env python3
"""Request queue management for worker pool.

Functions for fetching requests from the priority queue and checking completion status.
"""
from typing import Optional, Set
from queue import PriorityQueue, Empty

from infra.llm.models import LLMRequest


def get_next_request(
    worker_pool,
    queue: PriorityQueue,
    expected_ids: Set[str]
) -> Optional[LLMRequest]:
    """Get next request from queue, or None if queue empty.

    Returns None if:
    - Queue is empty after timeout
    - All expected requests are already done
    """
    try:
        return queue.get(timeout=0.5)
    except Empty:
        if check_if_all_done(worker_pool, expected_ids):
            return None
        return None


def check_if_all_done(worker_pool, expected_ids: Set[str]) -> bool:
    """Check if all expected requests have completed."""
    with worker_pool.results_lock:
        return len(worker_pool.results) >= len(expected_ids)
