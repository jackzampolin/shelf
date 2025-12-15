from dataclasses import dataclass
from typing import Optional
from infra.pipeline.status import PhaseStatusTracker
from .provider import OCRProvider


@dataclass
class OCRBatchConfig:
    tracker: PhaseStatusTracker
    provider: OCRProvider
    batch_name: Optional[str] = None  # Defaults to provider.name if not set
    max_workers: int = 10
    silent: bool = False  # Suppress progress display (for parallel execution)
