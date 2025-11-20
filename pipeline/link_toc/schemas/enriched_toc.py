from typing import Optional, List, Literal
from pydantic import BaseModel, Field


class EnrichedToCEntry(BaseModel):
    """Entry in enriched ToC (flat structure with parent pointers)."""

    entry_index: int = Field(..., ge=0, description="Position in flat list")
    title: str = Field(..., min_length=1, description="Entry title")
    scan_page: int = Field(..., ge=1, description="Scan page where entry appears")
    level: int = Field(..., ge=1, le=3, description="Hierarchy level (1=top, 2=child, 3=grandchild)")

    parent_index: Optional[int] = Field(None, description="Index of parent entry (null for top-level)")
    source: Literal["toc", "discovered"] = Field(..., description="Where did this come from?")

    # Original ToC fields (if source="toc")
    entry_number: Optional[str] = Field(None, description="Entry numbering from ToC")
    printed_page_number: Optional[str] = Field(None, description="Printed page number from ToC")

    # Discovered fields (if source="discovered")
    discovery_reasoning: Optional[str] = Field(None, description="Why was this included?")
    label_structure_level: Optional[int] = Field(None, description="Original level from label-structure")


class EnrichedTableOfContents(BaseModel):
    """Table of Contents enriched with discovered headings."""

    entries: List[EnrichedToCEntry] = Field(..., description="All entries (ToC + discovered), flat with parent pointers")

    # Statistics
    original_toc_count: int = Field(..., ge=0, description="Count of original ToC entries")
    discovered_count: int = Field(..., ge=0, description="Count of discovered headings added")
    total_entries: int = Field(..., ge=0, description="Total entries in enriched ToC")

    # Metadata
    pattern_confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence from pattern analysis")
    pattern_description: str = Field(..., description="Pattern identified in analysis")
