#!/usr/bin/env python3
from dataclasses import dataclass
from typing import Optional


@dataclass
class LLMBatchConfig:
    model: str
    max_workers: Optional[int] = None
    max_retries: int = 3
    retry_jitter: tuple = (1.0, 3.0)
    batch_name: str = "LLM Batch"
