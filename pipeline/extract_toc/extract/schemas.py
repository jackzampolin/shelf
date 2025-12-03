"""Schemas for single-call ToC extraction."""

from typing import List, Optional
from pydantic import BaseModel, Field


class ExtractedToCEntry(BaseModel):
    """A single ToC entry extracted from the complete ToC."""
    entry_number: Optional[str] = Field(
        None,
        description="Entry numbering if present (e.g., '5', 'II', 'A', '1.1')"
    )
    title: str = Field(
        ...,
        description="Entry title as shown in ToC. Empty string '' for standalone markers like 'PART I'."
    )
    level: int = Field(
        1,
        ge=1,
        le=3,
        description="Visual hierarchy level (1=top-level, 2=nested, 3=deeply nested)"
    )
    level_name: Optional[str] = Field(
        None,
        description="Semantic type: 'part', 'chapter', 'section', 'appendix', 'prologue', 'epilogue', 'introduction', 'notes', 'bibliography', 'index', etc."
    )
    printed_page_number: Optional[str] = Field(
        None,
        description="Page number exactly as printed (roman 'ix' or arabic '15')"
    )


class ToCExtractionOutput(BaseModel):
    """Complete ToC extraction result."""
    entries: List[ExtractedToCEntry] = Field(
        ...,
        description="All ToC entries in top-to-bottom order"
    )
