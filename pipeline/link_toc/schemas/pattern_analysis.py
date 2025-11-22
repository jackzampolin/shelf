from typing import List, Dict, Tuple, Optional
from pydantic import BaseModel, Field


class CandidateHeading(BaseModel):
    """Heading discovered by label-structure that's not in ToC."""

    scan_page: int = Field(..., ge=1, description="Page where heading appears")
    heading_text: str = Field(..., description="Heading text from label-structure")
    heading_level: int = Field(..., ge=1, description="Level from label-structure (1=top, higher=more nested)")

    # Context
    preceding_toc_page: Optional[int] = Field(None, description="Scan page of preceding ToC entry")
    following_toc_page: Optional[int] = Field(None, description="Scan page of following ToC entry")


class MissingCandidateHeading(BaseModel):
    """Prediction about a heading that should exist but wasn't detected."""

    identifier: str = Field(..., description="Expected identifier (e.g., '9', 'Chapter IX', 'Part III')")
    predicted_page_range: Tuple[int, int] = Field(..., description="(earliest_possible, latest_possible) scan pages")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in this prediction")
    reasoning: str = Field(..., description="Why this heading is expected and where it likely is")


class ExcludedPageRange(BaseModel):
    """Page range to exclude from candidate evaluation."""

    start_page: int = Field(..., ge=1, description="First page of excluded range")
    end_page: int = Field(..., ge=1, description="Last page of excluded range")
    reason: str = Field(..., description="Why these pages should be excluded (e.g., 'Map pages', 'Notes section', 'Image gallery')")


class PatternAnalysis(BaseModel):
    """Analysis of ToC structure and discovered headings patterns."""

    # Pattern description
    pattern_description: str = Field(..., description="Human-readable pattern summary")
    expected_relationship: str = Field(
        ...,
        description="Expected relationship (e.g., 'chapters_under_parts', 'sections_under_chapters', 'fill_gaps')"
    )

    # Body range (where to focus enrichment)
    body_range: Tuple[int, int] = Field(..., description="(first_toc_page, last_toc_page)")

    # ToC structure analysis
    toc_structure: Dict = Field(
        ...,
        description="ToC analysis: {numbering: str, level: int, count: int, ascending_pages: bool}"
    )

    # Discovered headings analysis
    discovered_structure: Dict = Field(
        ...,
        description="Discovered headings: {count: int, numbering: str, levels: List[int]}"
    )

    # Filtered candidates
    candidate_headings: List[CandidateHeading] = Field(
        ...,
        description="Headings in body range, filtered and contextualized"
    )

    # LLM observations for evaluation agents
    observations: List[str] = Field(
        default_factory=list,
        description="High-level observations about patterns in the candidate headings"
    )

    # Missing candidate heading predictions
    missing_candidate_headings: List[MissingCandidateHeading] = Field(
        default_factory=list,
        description="Headings expected based on patterns but not detected by label-structure"
    )

    # Page ranges to exclude from evaluation
    excluded_page_ranges: List[ExcludedPageRange] = Field(
        default_factory=list,
        description="Page ranges that should be excluded from candidate evaluation"
    )

    # Confidence
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in pattern analysis")
    reasoning: str = Field(..., description="Why this pattern was identified")
