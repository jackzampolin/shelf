"""OCR v2 schemas - all data structures with Pydantic validation."""

from .ocr_page_schemas import (
    BoundingBox,
    PageDimensions,
    Word,
    Line,
    Paragraph,
    Block,
    ImageRegion,
    OCRPageOutput,
    OCRPageMetrics as OldOCRPageMetrics,  # From old OCR
    OCRPageReport,
)

from .provider_schemas import (
    ProviderSelection,
    ProviderOutput,
    VisionSelectionResponse,
    OCRPageMetrics,  # OCR v2 version
)

__all__ = [
    # Spatial and structure schemas
    "BoundingBox",
    "PageDimensions",
    "Word",
    "Line",
    "Paragraph",
    "Block",
    "ImageRegion",
    # Page schemas
    "OCRPageOutput",
    "OCRPageReport",
    # Provider schemas
    "ProviderSelection",
    "ProviderOutput",
    "VisionSelectionResponse",
    "OCRPageMetrics",
]
