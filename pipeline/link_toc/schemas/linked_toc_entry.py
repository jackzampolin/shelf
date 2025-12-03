from typing import Optional
from pydantic import BaseModel, Field


class LinkedToCEntry(BaseModel):
    """ToC entry with scan page link.

    All fields from extract-toc ToCEntry plus scan page link.
    """

    # FROM EXTRACT-TOC (original entry) - must match ToCEntry constraints
    entry_number: Optional[str] = Field(None, description="Entry numbering (e.g., '5', 'II', 'A', '1.1')")
    title: str = Field(..., description="Entry title from ToC. Empty string '' for standalone markers like 'PART I'.")
    level: int = Field(..., ge=1, description="Hierarchy level (1=top, higher=more nested)")
    level_name: Optional[str] = Field(None, description="Semantic type: 'chapter', 'part', 'section', etc")
    printed_page_number: Optional[str] = Field(None, description="Printed page number from ToC")

    # FROM LINK-TOC (just the link!)
    scan_page: Optional[int] = Field(None, ge=1, description="Scan page where entry appears (None if not found)")
    agent_reasoning: str = Field(..., description="How agent found this entry or why it couldn't")
