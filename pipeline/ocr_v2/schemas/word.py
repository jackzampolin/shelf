"""Word schema for OCR text detection."""

from pydantic import BaseModel, Field, field_validator

from .bounding_box import BoundingBox


class Word(BaseModel):
    """
    A single word detected by Tesseract.

    Word-level detail for targeted analysis (not used in correction).
    """
    text: str = Field(..., min_length=1, description="Word text")
    bbox: BoundingBox = Field(..., description="Word bounding box")
    confidence: float = Field(..., ge=0.0, le=1.0, description="OCR confidence for this word (0.0-1.0)")

    @field_validator('bbox', mode='before')
    @classmethod
    def parse_bbox(cls, v):
        """Handle bbox as list or BoundingBox."""
        if isinstance(v, list):
            return BoundingBox.from_list(v)
        return v
