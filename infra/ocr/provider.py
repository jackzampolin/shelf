"""
OCR provider interface for standardizing different OCR implementations.

Each OCR provider (OlmOCR, Mistral, OpenAI, etc.) implements this interface
to enable plug-and-play architecture with shared batch processing infrastructure.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict
from PIL import Image


@dataclass
class OCRResult:
    """
    Standardized OCR result across all providers.

    Attributes:
        success: Whether OCR succeeded
        text: Primary extracted text (markdown/plain text)
        metadata: Provider-specific metadata (dimensions, language, etc.)

        cost_usd: Cost in USD for this request
        prompt_tokens: Input tokens used (if applicable)
        completion_tokens: Output tokens generated (if applicable)
        execution_time_seconds: Time spent processing

        error_message: Error description if success=False
        retry_count: Number of retries attempted before success/failure
    """
    success: bool
    text: str
    metadata: Dict[str, Any]

    # Telemetry
    cost_usd: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    execution_time_seconds: float = 0.0

    # Error tracking
    error_message: str = None
    retry_count: int = 0


class OCRProvider(ABC):
    """
    Abstract interface for OCR providers.

    Each provider (OlmOCR, Mistral, etc.) implements this interface to provide:
    - Image processing logic
    - Result persistence (save to disk + record metrics)
    - Rate limiting configuration
    - Retry strategy configuration
    """

    def __init__(self, stage_storage):
        """
        Initialize provider with stage storage for persistence.

        Args:
            stage_storage: StageStorage instance for saving pages and metrics
        """
        self.stage_storage = stage_storage

    @abstractmethod
    def process_image(self, image: Image.Image, page_num: int) -> OCRResult:
        """
        Process a single image and return OCR result.

        Args:
            image: PIL Image to process
            page_num: Page number for logging/tracking

        Returns:
            OCRResult with extracted text and metadata

        Note:
            This method should NOT handle retries - that's handled by the batch processor.
            Just attempt the OCR call once and return success/failure.
        """
        pass

    @abstractmethod
    def handle_result(self, page_num: int, result: OCRResult):
        """
        Handle successful OCR result - save to disk and record metrics.

        Args:
            page_num: Page number
            result: OCRResult from process_image()

        Note:
            Provider knows its own schema and how to persist results.
            Stage shouldn't need to know about provider-specific metadata fields.
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name (e.g., 'olmocr', 'mistral')"""
        pass

    @property
    def requests_per_second(self) -> float:
        """
        Rate limit for this provider in requests per second.

        Returns:
            float('inf') for no rate limit, otherwise requests/sec (e.g., 6.0)
        """
        return float('inf')

    @property
    def max_retries(self) -> int:
        """
        Number of retry attempts on failure.

        Returns:
            Number of retries (0 = no retries, 3 = try up to 3 times after initial failure)
        """
        return 3

    @property
    def retry_delay_base(self) -> float:
        """
        Base delay in seconds for exponential backoff.

        Delay formula: retry_delay_base ** attempt
        - Attempt 0: 1.0s (2^0)
        - Attempt 1: 2.0s (2^1)
        - Attempt 2: 4.0s (2^2)

        Returns:
            Base delay in seconds (default: 2.0)
        """
        return 2.0
