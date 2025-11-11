"""OCR infrastructure for standardized provider implementations."""

from .provider import OCRProvider, OCRResult
from .batch_processor import OCRBatchProcessor

__all__ = [
    "OCRProvider",
    "OCRResult",
    "OCRBatchProcessor",
]
