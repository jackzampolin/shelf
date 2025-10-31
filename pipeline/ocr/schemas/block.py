from typing import List, Optional
from pydantic import BaseModel, Field, field_validator

from .bounding_box import BoundingBox
from .paragraph import Paragraph


class Block(BaseModel):
    block_num: int = Field(..., ge=0, description="Tesseract block number")
    bbox: BoundingBox = Field(..., description="Block bounding box")
    paragraphs: List[Paragraph] = Field(default_factory=list, description="Paragraphs in this block")

    block_type_hint: Optional[str] = Field(None, description="Block type hint from hOCR (e.g. 'text', 'header', 'footer')")
    reading_order: Optional[int] = Field(None, description="Reading order hint from hOCR")

    @field_validator('bbox', mode='before')
    @classmethod
    def parse_bbox(cls, v):
        if isinstance(v, list):
            return BoundingBox.from_list(v)
        return v

    @field_validator('paragraphs')
    @classmethod
    def validate_paragraphs(cls, paragraphs):
        if len(paragraphs) == 0:
            raise ValueError("Block must contain at least one paragraph")
        return paragraphs

    @property
    def is_isolated(self) -> bool:
        return len(self.paragraphs) == 1

    @property
    def text(self) -> str:
        return "\n\n".join(p.text for p in self.paragraphs)
