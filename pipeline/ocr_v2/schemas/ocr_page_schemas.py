"""
OCR Output Schemas - Hierarchical Layout Structure

Based on Tesseract's block/paragraph detection.
Preserves spatial layout intelligence without word/line bloat.

Design philosophy:
- Trust Tesseract's block detection (isolated vs continuous regions)
- Keep paragraph-level text (the unit LLMs actually correct)
- Preserve spatial bboxes (for visual context alignment)
- Skip line/word detail (saves 6x on multimodal input costs)

For correction stage:
- LLM receives: PDF page image + this structure
- Visual + spatial context enables smart corrections
- Block structure enables semantic classification
"""

from typing import List, Literal, Optional, Tuple
from pydantic import BaseModel, Field, field_validator


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

    @property
    def y_center(self) -> float:
        """Y coordinate of center point."""
        return self.y + (self.height / 2)


class PageDimensions(BaseModel):
    """Page dimensions in pixels."""
    width: int = Field(..., ge=1, description="Page width in pixels")
    height: int = Field(..., ge=1, description="Page height in pixels")


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


class Block(BaseModel):
    """
    A text block detected by Tesseract.

    Tesseract's block detection identifies spatially isolated regions:
    - Headers/footers (isolated at top/bottom)
    - Columns (side-by-side continuous regions)
    - Body text (large continuous region)
    - Captions (small isolated near images)

    This structure is gold - don't classify it, just preserve it for the LLM.
    """
    block_num: int = Field(..., ge=0, description="Tesseract block number")
    bbox: BoundingBox = Field(..., description="Block bounding box")
    paragraphs: List[Paragraph] = Field(default_factory=list, description="Paragraphs in this block")

    # Hints from hOCR (optional, not authoritative)
    block_type_hint: Optional[str] = Field(None, description="Block type hint from hOCR (e.g. 'text', 'header', 'footer')")
    reading_order: Optional[int] = Field(None, description="Reading order hint from hOCR")

    @field_validator('bbox', mode='before')
    @classmethod
    def parse_bbox(cls, v):
        """Handle bbox as list or BoundingBox."""
        if isinstance(v, list):
            return BoundingBox.from_list(v)
        return v

    @field_validator('paragraphs')
    @classmethod
    def validate_paragraphs(cls, paragraphs):
        """Ensure paragraphs is not empty."""
        if len(paragraphs) == 0:
            raise ValueError("Block must contain at least one paragraph")
        return paragraphs

    @property
    def is_isolated(self) -> bool:
        """
        Heuristic: single-paragraph blocks are likely isolated elements.
        (headers, footers, captions, page numbers)
        """
        return len(self.paragraphs) == 1

    @property
    def text(self) -> str:
        """Get all text in block concatenated."""
        return "\n\n".join(p.text for p in self.paragraphs)


class ImageRegion(BaseModel):
    """
    An image region detected on page.

    Detected via OpenCV contour analysis, validated by OCR.
    Only confirmed images (not decorative text) are saved.
    """
    image_id: int = Field(..., ge=1, description="Unique image ID within page")
    bbox: BoundingBox = Field(..., description="Image bounding box")
    image_file: str = Field(..., description="Saved image filename")

    # Validation metadata
    ocr_attempted: bool = Field(True, description="Whether OCR validation was attempted")
    ocr_text_recovered: Optional[str] = Field(None, description="If text found during validation, moved to blocks instead")

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
    Designed to be input to correction stage (multimodal LLM).
    """
    page_number: int = Field(..., ge=1, description="Page number in book")
    page_dimensions: PageDimensions = Field(..., description="Page dimensions")
    ocr_timestamp: str = Field(..., description="ISO format timestamp")

    blocks: List[Block] = Field(default_factory=list, description="Text blocks detected by Tesseract")
    images: List[ImageRegion] = Field(default_factory=list, description="Images detected via OpenCV")

    @field_validator('blocks')
    @classmethod
    def validate_blocks(cls, blocks):
        """Ensure block numbers are unique."""
        block_nums = [b.block_num for b in blocks]
        if len(block_nums) != len(set(block_nums)):
            raise ValueError("Block numbers must be unique within page")
        return blocks

    @field_validator('images')
    @classmethod
    def validate_images(cls, images):
        """Ensure image IDs are unique."""
        image_ids = [img.image_id for img in images]
        if len(image_ids) != len(set(image_ids)):
            raise ValueError("Image IDs must be unique within page")
        return images

    def get_isolated_blocks(self) -> List[Block]:
        """Get likely headers/footers/captions (single-paragraph blocks)."""
        return [b for b in self.blocks if b.is_isolated]

    def get_continuous_blocks(self) -> List[Block]:
        """Get likely body text (multi-paragraph blocks)."""
        return [b for b in self.blocks if not b.is_isolated]

    def get_all_text(self) -> str:
        """Get all text from all blocks concatenated."""
        return "\n\n".join(b.text for b in self.blocks)

    def find_nearby_blocks(self, image: ImageRegion, proximity: int = 100) -> List[Block]:
        """
        Find blocks near an image (for caption detection).

        Args:
            image: Image region to check
            proximity: Maximum distance in pixels

        Returns:
            List of blocks within proximity distance
        """
        nearby = []
        img_y = image.bbox.y_center

        for block in self.blocks:
            block_y = block.bbox.y_center
            distance = abs(img_y - block_y)

            if distance <= proximity:
                nearby.append(block)

        return nearby


# ============================================================================
# Checkpoint Metrics Schema
# ============================================================================


class OCRPageMetrics(BaseModel):
    """
    Checkpoint metrics for OCR stage.

    Tracks Tesseract OCR performance per page per PSM mode.
    OCR stage is unique - no LLM costs for pages, but tracks
    OCR quality metrics (confidence, blocks detected).
    """
    page_num: int = Field(..., ge=1, description="Page number processed")
    processing_time_seconds: float = Field(..., ge=0.0, description="Tesseract processing time")
    cost_usd: float = Field(0.0, ge=0.0, description="Cost (always 0 for Tesseract)")

    # OCR-specific metrics
    psm_mode: int = Field(..., ge=0, le=13, description="Tesseract PSM mode used")
    tesseract_version: str = Field(..., description="Tesseract version used")
    confidence_mean: float = Field(..., ge=0.0, le=1.0, description="Mean OCR confidence across page")
    blocks_detected: int = Field(..., ge=0, description="Number of text blocks detected")
    recovered_text_blocks_count: int = Field(0, ge=0, description="Number of text blocks recovered from image validation")


# ============================================================================
# Report Schema (Quality metrics only)
# ============================================================================


class OCRPageReport(BaseModel):
    """
    Quality-focused report for OCR stage.

    Minimal report to spot low-quality OCR pages.
    LLMs consume OCR directly, so just flag potential issues.
    """
    page_num: int = Field(..., ge=1, description="Page number")
    confidence_mean: float = Field(..., ge=0.0, le=1.0, description="Mean OCR confidence (low = poor quality)")
    blocks_detected: int = Field(..., ge=0, description="Text blocks detected (abnormal values = layout issues)")
