"""Block schema for OCR text detection."""

from typing import List, Optional
from pydantic import BaseModel, Field, field_validator

from .bounding_box import BoundingBox
from .paragraph import Paragraph


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
