from typing import List, Tuple, Optional, Literal
from pydantic import BaseModel, Field


class CandidateHeading(BaseModel):
    scan_page: int = Field(..., ge=1)
    heading_text: str
    heading_level: int = Field(..., ge=1)
    preceding_toc_page: Optional[int] = None
    following_toc_page: Optional[int] = None
    toc_entry_on_page: Optional[str] = None
    # From label-structure unified output
    label_running_header: Optional[str] = None
    label_page_number: Optional[str] = None


class MissingEntry(BaseModel):
    """An entry expected by a sequential pattern but not found in candidates."""
    identifier: str  # "14", "III", "Part II"
    predicted_page_range: Tuple[int, int]
    level_name: Optional[str] = None  # "chapter", "part" - from parent pattern
    level: Optional[int] = None  # hierarchy level - from parent pattern
    # Pattern context for search agent
    pattern_description: Optional[str] = None  # "chapters 1-38"
    pattern_found: Optional[int] = None  # 36 (how many found)
    pattern_expected: Optional[int] = None  # 38 (how many expected)
    avg_pages_per_entry: Optional[int] = None  # ~13 pages per chapter


class DiscoveredPattern(BaseModel):
    """A structural pattern detected in candidate headings."""
    pattern_type: Literal["sequential", "named"]
    level_name: Optional[str] = None  # "chapter", "part", "appendix", "conclusion"
    range_start: Optional[str] = None  # "1", "I", "A" (for sequential)
    range_end: Optional[str] = None  # "38", "X", "F"
    level: Optional[int] = None  # 1=part, 2=chapter, 3=section
    # The actual heading format observed in the book's candidate headings
    # e.g., "CHAPTER {n}" if headings are "CHAPTER 1", "CHAPTER 2"
    # e.g., "{n}" if headings are just "1", "2", "3"
    heading_format: Optional[str] = None
    action: Literal["include", "exclude"]
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)  # sequential: found/expected
    missing_entries: List[MissingEntry] = Field(default_factory=list)  # sequential only
    reasoning: str


class ExcludedPageRange(BaseModel):
    """Page ranges to skip entirely (Notes, Bibliography, Index)."""
    start_page: int = Field(..., ge=1)
    end_page: int = Field(..., ge=1)
    reason: str


class PatternAnalysis(BaseModel):
    body_range: Tuple[int, int]
    candidate_headings: List[CandidateHeading]
    discovered_patterns: List[DiscoveredPattern] = Field(default_factory=list)
    excluded_page_ranges: List[ExcludedPageRange] = Field(default_factory=list)
    requires_evaluation: bool = True
    reasoning: str = ""


# Backwards compatibility - keep old name as alias
MissingCandidateHeading = MissingEntry
