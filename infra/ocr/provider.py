from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict
from PIL import Image


@dataclass
class OCRResult:
    success: bool
    text: str
    metadata: Dict[str, Any]

    cost_usd: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    execution_time_seconds: float = 0.0

    error_message: str = None
    retry_count: int = 0


class OCRProvider(ABC):
    def __init__(self, stage_storage):
        self.stage_storage = stage_storage

    @abstractmethod
    def process_image(self, image: Image.Image, page_num: int) -> OCRResult:
        pass

    @abstractmethod
    def handle_result(self, page_num: int, result: OCRResult, output_dir=None):
        """Handle OCR result - save to disk and record metrics.

        Args:
            page_num: Page number being processed
            result: OCR result to handle
            output_dir: Optional output directory (defaults to stage_storage.output_dir)
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    def requests_per_second(self) -> float:
        return float('inf')

    @property
    def max_retries(self) -> int:
        return 3

    @property
    def retry_delay_base(self) -> float:
        return 2.0
