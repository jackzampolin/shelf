from typing import List, Tuple, Optional
from pydantic import BaseModel, Field


class CandidateHeading(BaseModel):
    scan_page: int = Field(..., ge=1)
    heading_text: str
    heading_level: int = Field(..., ge=1)
    preceding_toc_page: Optional[int] = None
    following_toc_page: Optional[int] = None


class MissingCandidateHeading(BaseModel):
    identifier: str
    predicted_page_range: Tuple[int, int]
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: str


class ExcludedPageRange(BaseModel):
    start_page: int = Field(..., ge=1)
    end_page: int = Field(..., ge=1)
    reason: str


class PatternAnalysis(BaseModel):
    body_range: Tuple[int, int]
    candidate_headings: List[CandidateHeading]
    observations: List[str] = Field(default_factory=list)
    missing_candidate_headings: List[MissingCandidateHeading] = Field(default_factory=list)
    excluded_page_ranges: List[ExcludedPageRange] = Field(default_factory=list)
    requires_evaluation: bool = True
    reasoning: str = ""
