#!/usr/bin/env python3
import time
from typing import Dict

from ..schemas import RequestPhase, BatchStats


def aggregate_batch_stats(
    metrics_manager,
    active_requests: Dict,
    total_requests: int,
    rate_limit_status: Dict,
    batch_start_time: float
) -> BatchStats:
    all_metrics = metrics_manager.get_all() if metrics_manager else {}
    completed_count = len(all_metrics)

    if not all_metrics:
        return BatchStats()

    total_cost = 0.0
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_reasoning_tokens = 0
    failed_count = 0
    times = []

    for metrics in all_metrics.values():
        total_cost += metrics.get('cost_usd', 0.0)
        total_prompt_tokens += metrics.get('prompt_tokens', 0)
        total_completion_tokens += metrics.get('completion_tokens', 0)
        total_reasoning_tokens += metrics.get('reasoning_tokens', 0)

        if metrics.get('error_type') or not metrics.get('success', True):
            failed_count += 1

        times.append(metrics.get('time_seconds', 0.0))

    avg_time = sum(times) / len(times) if times else 0.0
    min_time = min(times) if times else 0.0
    max_time = max(times) if times else 0.0
    avg_cost = total_cost / completed_count if completed_count > 0 else 0.0
    avg_tokens = total_completion_tokens / completed_count if completed_count > 0 else 0.0

    elapsed = time.time() - batch_start_time if batch_start_time else 0.0
    requests_per_second = completed_count / elapsed if elapsed > 0 else 0.0

    in_progress_count = len([
        s for s in active_requests.values()
        if s.phase in (RequestPhase.EXECUTING, RequestPhase.DEQUEUED, RequestPhase.RATE_LIMITED)
    ])

    queued = max(0, total_requests - completed_count - in_progress_count)

    return BatchStats(
        total_requests=total_requests,
        completed=completed_count,
        failed=failed_count,
        in_progress=in_progress_count,
        queued=queued,
        avg_time_per_request=avg_time,
        min_time=min_time,
        max_time=max_time,
        total_cost_usd=total_cost,
        avg_cost_per_request=avg_cost,
        total_prompt_tokens=total_prompt_tokens,
        total_tokens=total_completion_tokens,
        total_reasoning_tokens=total_reasoning_tokens,
        avg_tokens_per_request=avg_tokens,
        requests_per_second=requests_per_second,
        rate_limit_utilization=rate_limit_status.get('utilization', 0.0),
        rate_limit_tokens_available=rate_limit_status.get('tokens_available', 0)
    )
