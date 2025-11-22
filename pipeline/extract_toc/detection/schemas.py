"""Schemas for detection phase structured output."""

from typing import List, Optional
from pydantic import BaseModel, Field


class DetectionEntry(BaseModel):
    """A single ToC entry extracted from a page."""
    entry_number: Optional[str] = Field(
        None,
        description="Entry numbering if present (e.g., '5', 'II', 'A', '1.1')"
    )
    title: str = Field(
        ...,
        description="Entry title text. Use empty string '' for standalone markers like 'PART I' that have no title."
    )
    level: int = Field(
        1,
        ge=1,
        le=3,
        description="Visual hierarchy level: 1=flush left, 2=indented, 3=deeply indented"
    )
    level_name: Optional[str] = Field(
        None,
        description="Semantic type: 'part', 'chapter', 'section', 'appendix', 'notes', 'index', etc."
    )
    printed_page_number: Optional[str] = Field(
        None,
        description="Page number from right side of entry (e.g., '15', 'ix', 'xiii')"
    )


class PageMetadata(BaseModel):
    """Metadata about the page extraction."""
    continuation_from_previous: bool = Field(
        False,
        description="True if this page continues entries from previous page"
    )
    continues_to_next: bool = Field(
        False,
        description="True if entries continue on next page"
    )


class PageExtractionOutput(BaseModel):
    """Structured output for ToC page extraction."""
    entries: List[DetectionEntry] = Field(
        ...,
        description="All ToC entries found on this page, in order from top to bottom"
    )
    page_metadata: PageMetadata = Field(
        default_factory=PageMetadata,
        description="Metadata about page continuity"
    )
    confidence: float = Field(
        0.95,
        ge=0.0,
        le=1.0,
        description="Confidence in extraction accuracy (0.0-1.0)"
    )
    notes: str = Field(
        "",
        description="Optional observations about extraction challenges or anomalies"
    )
