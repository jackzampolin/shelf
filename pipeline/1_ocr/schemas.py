"""
OCR Output Schemas

Based on:
1. Tesseract's official TSV/DICT output format
2. Observed output from running OCR on test books
3. Requirements from downstream correction stage

References:
- Tesseract TSV format: level, page_num, block_num, par_num, line_num, word_num,
  left, top, width, height, conf, text
- pytesseract Output.DICT provides same fields as dict
"""

from typing import List, Literal, Optional
from pydantic import BaseModel, Field, field_validator


class PageDimensions(BaseModel):
    """Page dimensions in pixels."""
    width: int = Field(..., ge=1, description="Page width in pixels")
    height: int = Field(..., ge=1, description="Page height in pixels")


class BoundingBox(BaseModel):
    """Bounding box coordinates [x, y, width, height]."""
    x: int = Field(..., ge=0, description="X coordinate of top-left corner")
    y: int = Field(..., ge=0, description="Y coordinate of top-left corner")
    width: int = Field(..., ge=0, description="Width of region")
    height: int = Field(..., ge=0, description="Height of region")

    @classmethod
    def from_list(cls, bbox: List[int]) -> "BoundingBox":
        """Create from [x, y, w, h] list."""
        if len(bbox) != 4:
            raise ValueError(f"BoundingBox requires 4 values, got {len(bbox)}")
        return cls(x=bbox[0], y=bbox[1], width=bbox[2], height=bbox[3])

    def to_list(self) -> List[int]:
        """Convert to [x, y, w, h] list."""
        return [self.x, self.y, self.width, self.height]


class TextRegion(BaseModel):
    """
    A text region on a page (paragraph, header, footer, or caption).

    This is our enhanced output format that aggregates Tesseract's word-level
    output into semantic regions with classification.
    """
    id: int = Field(..., ge=1, description="Unique region ID within page")
    type: Literal["header", "footer", "caption", "body"] = Field(
        ..., description="Region type based on position and content"
    )
    bbox: BoundingBox = Field(..., description="Region bounding box")
    text: str = Field(..., min_length=1, description="Text content")
    confidence: float = Field(..., ge=0.0, le=1.0, description="OCR confidence (0.0-1.0)")
    reading_order: int = Field(..., ge=1, description="Reading order index")
    associated_image: Optional[int] = Field(
        None, description="ID of associated image (for captions)"
    )

    @field_validator('bbox', mode='before')
    @classmethod
    def parse_bbox(cls, v):
        """Handle bbox as list or BoundingBox."""
        if isinstance(v, list):
            return BoundingBox.from_list(v)
        return v


class ImageRegion(BaseModel):
    """An image region detected on a page."""
    id: int = Field(..., ge=1, description="Unique region ID within page")
    type: Literal["image"] = "image"
    bbox: BoundingBox = Field(..., description="Image bounding box")
    image_file: str = Field(..., description="Saved image filename")
    reading_order: int = Field(..., ge=1, description="Reading order index")

    @field_validator('bbox', mode='before')
    @classmethod
    def parse_bbox(cls, v):
        """Handle bbox as list or BoundingBox."""
        if isinstance(v, list):
            return BoundingBox.from_list(v)
        return v


class OCRPageOutput(BaseModel):
    """
    Complete OCR output for a single page.

    This is the schema we save to page_XXXX.json files.
    """
    page_number: int = Field(..., ge=1, description="Page number in book")
    page_dimensions: PageDimensions = Field(..., description="Page dimensions")
    ocr_timestamp: str = Field(..., description="ISO format timestamp")
    ocr_mode: Literal["structured"] = "structured"
    regions: List[TextRegion | ImageRegion] = Field(
        default_factory=list, description="Text and image regions"
    )

    @field_validator('regions')
    @classmethod
    def validate_unique_ids(cls, regions):
        """Ensure region IDs are unique within page."""
        ids = [r.id for r in regions]
        if len(ids) != len(set(ids)):
            raise ValueError("Region IDs must be unique within page")
        return regions

    def get_text_regions(self) -> List[TextRegion]:
        """Get only text regions."""
        return [r for r in self.regions if isinstance(r, TextRegion)]

    def get_image_regions(self) -> List[ImageRegion]:
        """Get only image regions."""
        return [r for r in self.regions if isinstance(r, ImageRegion)]

    def get_body_text(self) -> str:
        """Get all body text concatenated."""
        body_regions = [r for r in self.regions if isinstance(r, TextRegion) and r.type == "body"]
        return "\n\n".join(r.text for r in sorted(body_regions, key=lambda x: x.reading_order))


# ============================================================================
# Tesseract Raw Output Schemas (for reference and potential future use)
# ============================================================================

class TesseractWordData(BaseModel):
    """
    Single word from Tesseract's TSV/DICT output.

    This matches Tesseract's official output format at level=5 (word level).
    We may use this in the future for more fine-grained processing.
    """
    level: Literal[5] = Field(..., description="Always 5 for word level")
    page_num: int = Field(..., ge=1)
    block_num: int = Field(..., ge=0)
    par_num: int = Field(..., ge=0)
    line_num: int = Field(..., ge=0)
    word_num: int = Field(..., ge=0)
    left: int = Field(..., ge=0, description="X coordinate")
    top: int = Field(..., ge=0, description="Y coordinate")
    width: int = Field(..., ge=0)
    height: int = Field(..., ge=0)
    conf: int = Field(..., ge=-1, le=100, description="Confidence 0-100, -1 for empty")
    text: str = Field(..., description="Word text (may be empty)")

    @property
    def bbox(self) -> BoundingBox:
        """Get bounding box."""
        return BoundingBox(x=self.left, y=self.top, width=self.width, height=self.height)

    @property
    def confidence_normalized(self) -> float:
        """Get confidence as 0.0-1.0 float."""
        return max(0.0, self.conf / 100.0)
