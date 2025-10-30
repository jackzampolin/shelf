"""Line schema for OCR text detection."""

from typing import List, Optional, Tuple
from pydantic import BaseModel, Field, field_validator

from .bounding_box import BoundingBox
from .word import Word


class Line(BaseModel):
    """
    A text line detected by Tesseract.

    Preserves line breaks and hyphenation context.
    Typography metadata enables font size-based classification.
    """
    line_num: int = Field(..., ge=0, description="Tesseract line number within paragraph")
    text: str = Field(..., min_length=1, description="Full line text (all words joined)")
    bbox: BoundingBox = Field(..., description="Line bounding box")
    words: List[Word] = Field(default_factory=list, description="Words in this line")
    avg_confidence: float = Field(..., ge=0.0, le=1.0, description="Average OCR confidence (0.0-1.0)")

    # Typography metadata from hOCR (optional)
    baseline: Optional[Tuple[float, float]] = Field(None, description="Baseline (slope, offset)")
    x_size: Optional[float] = Field(None, description="X-height (font size estimate)")
    x_ascenders: Optional[float] = Field(None, description="Ascender height")
    x_descenders: Optional[float] = Field(None, description="Descender height")

    @field_validator('bbox', mode='before')
    @classmethod
    def parse_bbox(cls, v):
        """Handle bbox as list or BoundingBox."""
        if isinstance(v, list):
            return BoundingBox.from_list(v)
        return v
