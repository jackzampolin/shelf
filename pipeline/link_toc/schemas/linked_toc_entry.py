from typing import Optional
from pydantic import BaseModel, Field


class LinkedToCEntry(BaseModel):
    """ToC entry enriched with scan page link.

    All fields from extract-toc ToCEntry plus linking information.
    """

    # FROM EXTRACT-TOC (original entry)
    entry_number: Optional[str] = Field(None, description="Entry numbering (e.g., '5', 'II', 'A', '1.1')")
    title: str = Field(..., min_length=1, description="Entry title from ToC")
    level: int = Field(..., ge=1, le=3, description="Hierarchy level (1=top, 2=nested, 3=deeply nested)")
    level_name: Optional[str] = Field(None, description="Semantic type: 'chapter', 'part', 'section', etc")
    printed_page_number: Optional[str] = Field(None, description="Printed page number from ToC")

    # FROM LINK-TOC (linking information)
    scan_page: Optional[int] = Field(None, ge=1, description="Scan page where entry appears (None if not found)")
    link_confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in scan_page link")

    # AGENT METADATA (debugging/verification)
    agent_reasoning: str = Field(..., description="How agent found this entry or why it couldn't")
    agent_iterations: int = Field(..., ge=0, description="Iterations agent used")
    candidates_checked: list[int] = Field(default_factory=list, description="Scan pages agent examined")
