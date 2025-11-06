from typing import Optional, List
from pydantic import BaseModel, Field


class AgentResult(BaseModel):
    """Result from TocEntryFinderAgent for a single ToC entry."""

    # Input context
    toc_entry_index: int = Field(..., ge=0, description="Index of ToC entry in original list")
    toc_title: str = Field(..., description="Title text from ToC entry")
    printed_page_number: Optional[str] = Field(None, description="Printed page number from ToC (if available)")

    # Search result
    found: bool = Field(..., description="Was the ToC entry found in the book?")
    scan_page: Optional[int] = Field(None, ge=1, description="Scan page number where entry was found (None if not found)")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in the match (0.0-1.0)")

    # Reasoning
    search_strategy: str = Field(..., description="Strategy used (e.g., 'boundary_text_match', 'page_number_lookup', 'sequential_search')")
    reasoning: str = Field(..., description="Explanation of how the page was found or why it wasn't found")
    iterations_used: int = Field(..., ge=0, description="Number of agent iterations used to find this entry")

    # Debugging
    candidates_checked: List[int] = Field(default_factory=list, description="List of scan pages the agent examined")
    notes: Optional[str] = Field(None, description="Additional notes or observations")
