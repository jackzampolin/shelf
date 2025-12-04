from pydantic import BaseModel, Field
from typing import List, Literal


class HeadingItem(BaseModel):
    level: int = Field(..., ge=1, le=6)
    text: str
    line_number: int


class PatternHints(BaseModel):
    has_footnote_refs: bool = False
    footnote_count: int = 0
    has_repeated_symbols: bool = False
    repeated_symbol: str = ""
    repeated_symbol_count: int = 0
    has_endnote_refs: bool = False
    endnote_markers: List[str] = Field(default_factory=list)
    has_images: bool = False
    image_refs: List[str] = Field(default_factory=list)


class MechanicalExtractionOutput(BaseModel):
    headings_present: bool
    headings: List[HeadingItem] = Field(default_factory=list)
    pattern_hints: PatternHints = Field(default_factory=PatternHints)
    source: Literal["blend-markdown"] = "blend-markdown"
    extraction_method: Literal["regex"] = "regex"


__all__ = [
    "HeadingItem",
    "PatternHints",
    "MechanicalExtractionOutput",
]
