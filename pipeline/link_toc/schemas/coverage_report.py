"""Coverage report schema for page coverage validation."""

from typing import List, Tuple, Optional, Literal
from pydantic import BaseModel, Field


class PageGap(BaseModel):
    """A gap in page coverage that needs investigation."""
    start_page: int = Field(..., ge=1)
    end_page: int = Field(..., ge=1)
    size: int = Field(..., ge=1)
    entry_before: Optional[str] = None  # Entry title before gap
    entry_before_page: Optional[int] = None
    entry_after: Optional[str] = None  # Entry title after gap
    entry_after_page: Optional[int] = None


class GapInvestigation(BaseModel):
    """Result of investigating a page gap."""
    gap: PageGap
    diagnosis: str
    fix_type: Optional[Literal["add_entry", "correct_entry", "no_fix_needed", "flagged"]] = None
    fix_details: Optional[str] = None
    flagged_for_review: bool = False
    flag_reason: Optional[str] = None


class CoverageReport(BaseModel):
    """Full coverage validation report."""
    body_range: Tuple[int, int]
    total_body_pages: int = Field(..., ge=0)
    entries_count: int = Field(..., ge=0)

    # Gap statistics
    gaps_found: int = Field(default=0, ge=0)
    gaps_fixed: int = Field(default=0, ge=0)
    gaps_no_fix_needed: int = Field(default=0, ge=0)
    gaps_flagged: int = Field(default=0, ge=0)

    # Coverage calculation
    pages_covered: int = Field(default=0, ge=0)
    coverage_percent: float = Field(default=0.0, ge=0.0, le=100.0)

    # Detailed investigations
    investigations: List[GapInvestigation] = Field(default_factory=list)

    # Overall status
    status: Literal["ok", "fixed", "needs_review"] = "ok"
