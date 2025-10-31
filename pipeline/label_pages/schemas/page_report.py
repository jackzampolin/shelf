"""
Report Schema

Quality-focused metrics for CSV report.
Filters checkpoint metrics to show only what matters for quality assessment.
"""

from typing import Optional, Literal
from pydantic import BaseModel, Field

from ..vision.schemas import PageRegion


class LabelPagesPageReport(BaseModel):
    """
    Quality-focused report for Label-Pages stage.

    Shows book structure and identifies classification issues:
    - Page numbering progression (gaps, style changes)
    - Region transitions (front → body → back matter)
    - Classification quality (low confidence, missing extractions)
    - Chapter/section boundaries (for build-structure stage)
    """
    page_num: int = Field(..., ge=1, description="PDF page number")
    printed_page_number: Optional[str] = Field(None, description="Printed page number on page (e.g., 'ix', '45', None)")
    numbering_style: Optional[Literal["roman", "arabic", "none"]] = Field(None, description="Page numbering style")
    page_region: Optional[PageRegion] = Field(None, description="Book region (front/body/back matter)")
    page_number_extracted: bool = Field(..., description="Was a printed page number found?")
    page_region_classified: bool = Field(..., description="Was page region identified?")
    total_blocks_classified: int = Field(..., ge=0, description="Blocks classified on this page")
    avg_classification_confidence: float = Field(..., ge=0.0, le=1.0, description="Classification quality (low = needs review)")

    # Chapter/section structure (for build-structure stage)
    has_chapter_heading: bool = Field(..., description="Does this page contain a CHAPTER_HEADING block?")
    has_section_heading: bool = Field(..., description="Does this page contain a SECTION_HEADING block?")
    chapter_heading_text: Optional[str] = Field(None, description="Text of chapter heading if present (first 100 chars)")
