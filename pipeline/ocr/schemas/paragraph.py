"""Paragraph schema for OCR text detection."""

from typing import List, Literal
from pydantic import BaseModel, Field, field_validator

from .bounding_box import BoundingBox
from .line import Line


class Paragraph(BaseModel):
    """
    A paragraph detected by Tesseract.

    Tesseract groups related text into paragraphs based on spatial proximity
    and text flow. This is the primary unit for LLM correction.
    """
    par_num: int = Field(..., ge=0, description="Tesseract paragraph number within block")
    bbox: BoundingBox = Field(..., description="Paragraph bounding box")
    text: str = Field(..., min_length=1, description="Full paragraph text (all lines joined)")
    lines: List[Line] = Field(default_factory=list, description="Lines in this paragraph")
    avg_confidence: float = Field(..., ge=0.0, le=1.0, description="Average OCR confidence (0.0-1.0)")

    # Source tracking for recovered text
    source: Literal["primary_ocr", "recovered_from_image"] = Field(
        "primary_ocr",
        description="Whether text came from normal OCR or was recovered from misclassified image"
    )

    @field_validator('bbox', mode='before')
    @classmethod
    def parse_bbox(cls, v):
        """Handle bbox as list or BoundingBox."""
        if isinstance(v, list):
            return BoundingBox.from_list(v)
        return v
