from dataclasses import dataclass
from typing import Optional, Callable
from ....pipeline.status.phase_tracker import PhaseStatusTracker

@dataclass
class LLMBatchConfig:
    tracker: PhaseStatusTracker
    model: str
    batch_name: str
    request_builder: Callable
    result_handler: Callable
    max_workers: Optional[int] = None
    max_retries: int = 7
    retry_jitter: tuple = (0.1, 0.5)
