from typing import Optional
from pydantic import BaseModel, Field


class HeadingDecision(BaseModel):
    """Decision on whether to include a candidate heading in enriched ToC."""

    # Input (what was evaluated)
    scan_page: int = Field(..., ge=1, description="Page where heading appears")
    heading_text: str = Field(..., description="Heading text from label-structure")

    # Decision
    include: bool = Field(..., description="Should this heading be included in enriched ToC?")

    # If include=True, enrichment details
    title: Optional[str] = Field(None, description="Cleaned/corrected heading text")
    level: Optional[int] = Field(None, ge=1, le=3, description="Level in enriched hierarchy")
    entry_number: Optional[str] = Field(None, description="Entry number if numbered (e.g., '5', 'V', 'A')")
    parent_toc_entry_index: Optional[int] = Field(None, description="Index of parent ToC entry")

    # Reasoning
    reasoning: str = Field(..., description="Why include or exclude this heading")
