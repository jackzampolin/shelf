"""OCR provider implementations for pluggable OCR backends."""

from .base import OCRProvider, OCRResult, OCRProviderConfig
from .tesseract import TesseractProvider

__all__ = [
    "OCRProvider",
    "OCRResult",
    "OCRProviderConfig",
    "TesseractProvider",
]
