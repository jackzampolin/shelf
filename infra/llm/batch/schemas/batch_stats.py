#!/usr/bin/env python3
from dataclasses import dataclass

@dataclass
class BatchStats:
    total_requests: int = 0
    completed: int = 0
    failed: int = 0
    in_progress: int = 0
    queued: int = 0
    avg_time_per_request: float = 0
    min_time: float = 0
    max_time: float = 0
    total_cost_usd: float = 0
    avg_cost_per_request: float = 0
    total_prompt_tokens: int = 0
    total_tokens: int = 0
    total_reasoning_tokens: int = 0
    avg_tokens_per_request: float = 0
    requests_per_second: float = 0
    rate_limit_utilization: float = 0
    rate_limit_tokens_available: int = 0
