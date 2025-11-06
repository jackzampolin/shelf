#!/usr/bin/env python3
import time
import threading
from typing import Dict, Any, List
from dataclasses import dataclass

@dataclass
class BatchStats:
    total_requests: int
    completed: int
    failed: int
    in_progress: int
    queued: int
    avg_time_per_request: float
    min_time: float
    max_time: float
    total_cost_usd: float
    avg_cost_per_request: float
    total_prompt_tokens: int
    total_tokens: int
    total_reasoning_tokens: int
    avg_tokens_per_request: float
    requests_per_second: float
    rate_limit_utilization: float
    rate_limit_tokens_available: int


class BatchStatsTracker:

    def __init__(self, batch_start_time: float = None):
        self.batch_start_time = batch_start_time or time.time()
        self._lock = threading.Lock()

        self._stats = {
            'total_cost_usd': 0.0,
            'total_prompt_tokens': 0,
            'total_tokens': 0,
            'total_reasoning_tokens': 0,
            'requests_completed': 0,
            'requests_failed': 0,
            'retry_count': 0,
        }

    def record_success(self, cost_usd: float, usage: Dict[str, Any]):
        with self._lock:
            self._stats['requests_completed'] += 1
            self._stats['total_cost_usd'] += cost_usd
            self._stats['total_prompt_tokens'] += usage.get('prompt_tokens', 0)
            self._stats['total_tokens'] += usage.get('completion_tokens', 0)

            completion_details = usage.get('completion_tokens_details', {})
            reasoning_tokens = completion_details.get('reasoning_tokens', 0)
            self._stats['total_reasoning_tokens'] += reasoning_tokens

    def record_failure(self):
        with self._lock:
            self._stats['requests_failed'] += 1

    def record_retry(self):
        with self._lock:
            self._stats['retry_count'] += 1

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return self._stats.copy()

    def get_batch_stats(
        self,
        total_requests: int,
        completed_results: Dict[str, 'LLMResult'],
        in_progress_count: int,
        rate_limit_status: Dict[str, Any]
    ) -> BatchStats:
        with self._lock:
            stats = self._stats.copy()

        completed_count = len(completed_results)
        if completed_results:
            times = [r.total_time_seconds for r in completed_results.values()]
            avg_time = sum(times) / len(times)
            min_time = min(times)
            max_time = max(times)
        else:
            avg_time = min_time = max_time = 0.0

        avg_cost = stats['total_cost_usd'] / completed_count if completed_count > 0 else 0.0

        elapsed = time.time() - self.batch_start_time
        requests_per_second = completed_count / elapsed if elapsed > 0 else 0.0

        queued = total_requests - completed_count - in_progress_count

        total_prompt_tokens = stats['total_prompt_tokens']
        total_tokens = stats['total_tokens']
        total_reasoning_tokens = stats['total_reasoning_tokens']
        avg_tokens = total_tokens / completed_count if completed_count > 0 else 0.0

        return BatchStats(
            total_requests=total_requests,
            completed=completed_count,
            failed=stats['requests_failed'],
            in_progress=in_progress_count,
            queued=max(0, queued),
            avg_time_per_request=avg_time,
            min_time=min_time,
            max_time=max_time,
            total_cost_usd=stats['total_cost_usd'],
            avg_cost_per_request=avg_cost,
            total_prompt_tokens=total_prompt_tokens,
            total_tokens=total_tokens,
            total_reasoning_tokens=total_reasoning_tokens,
            avg_tokens_per_request=avg_tokens,
            requests_per_second=requests_per_second,
            rate_limit_utilization=rate_limit_status.get('utilization', 0.0),
            rate_limit_tokens_available=rate_limit_status.get('tokens_available', 0)
        )
