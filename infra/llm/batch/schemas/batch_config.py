#!/usr/bin/env python3
from dataclasses import dataclass
from typing import Optional, Callable
from ....pipeline.status.batch_based import BatchBasedStatusTracker

@dataclass
class LLMBatchConfig:
    tracker: 'BatchBasedStatusTracker'
    model: str
    batch_name: str
    request_builder: Callable
    result_handler: Callable
    max_workers: Optional[int] = None
    max_retries: int = 3
    retry_jitter: tuple = (1.0, 3.0)
