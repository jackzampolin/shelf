#!/usr/bin/env python3
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
