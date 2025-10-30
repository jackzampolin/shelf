"""OCR page schemas - reusable across stages."""

from .page import (
    BoundingBox,
    PageDimensions,
    Word,
    Line,
    Paragraph,
    Block,
    ImageRegion,
    OCRPageOutput,
    OCRPageReport,
)

__all__ = [
    "BoundingBox",
    "PageDimensions",
    "Word",
    "Line",
    "Paragraph",
    "Block",
    "ImageRegion",
    "OCRPageOutput",
    "OCRPageReport",
]
