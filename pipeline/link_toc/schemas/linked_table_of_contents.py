from typing import List, Dict
from pydantic import BaseModel, Field

from .linked_toc_entry import LinkedToCEntry


class LinkedTableOfContents(BaseModel):
    """Table of Contents with all entries linked to scan pages.

    Output of link-toc stage - enriched ToC ready for chapter extraction.
    """

    # LINKED ENTRIES
    entries: List[LinkedToCEntry] = Field(..., description="All ToC entries with scan page links")

    # ORIGINAL TOC METADATA (passthrough from extract-toc)
    toc_page_range: Dict = Field(..., description="Where ToC appears (from extract-toc)")
    entries_by_level: Dict[int, int] = Field(..., description="Count per level (from extract-toc)")
    original_parsing_confidence: float = Field(..., ge=0.0, le=1.0, description="Extract-toc parsing confidence")

    # LINKING STATISTICS
    total_entries: int = Field(..., ge=0, description="Total entries attempted")
    linked_entries: int = Field(..., ge=0, description="Entries successfully linked")
    unlinked_entries: int = Field(..., ge=0, description="Entries not found")
    avg_link_confidence: float = Field(..., ge=0.0, le=1.0, description="Average confidence of linked entries")

    # COST TRACKING
    total_cost_usd: float = Field(..., ge=0.0, description="Total linking cost")
    total_time_seconds: float = Field(..., ge=0.0, description="Total processing time")
    avg_iterations_per_entry: float = Field(..., ge=0.0, description="Average agent iterations")
