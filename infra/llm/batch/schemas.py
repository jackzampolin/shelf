#!/usr/bin/env python3
from enum import Enum
from dataclasses import dataclass
from typing import Optional


class RequestPhase(str, Enum):
    QUEUED = "queued"
    RATE_LIMITED = "rate_limited"
    DEQUEUED = "dequeued"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class RequestStatus:
    request_id: str
    phase: RequestPhase
    queued_at: float
    phase_entered_at: float
    retry_count: int = 0
    rate_limit_eta: Optional[float] = None


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


@dataclass
class LLMBatchConfig:
    model: str
    max_workers: Optional[int] = None
    max_retries: int = 3
    retry_jitter: tuple = (1.0, 3.0)
    batch_name: str = "LLM Batch"
