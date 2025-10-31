"""
Checkpoint Metrics Schema

What we track in checkpoint for each page.
Extends LLMPageMetrics with label-specific quality metrics.
"""

from typing import Optional, Literal
from pydantic import Field
from infra.pipeline.schemas import LLMPageMetrics

from ..vision.schemas import PageRegion


class LabelPagesPageMetrics(LLMPageMetrics):
    """
    Checkpoint metrics for Label-Pages stage.

    Extends LLMPageMetrics with label-specific quality metrics.
    Tracks both LLM performance (tokens, timing, cost) and labeling
    quality (classification confidence, page number extraction success).

    Includes book structure fields for report generation.
    """
    # Label-specific metrics
    total_blocks_classified: int = Field(..., ge=0, description="Number of blocks classified")
    avg_classification_confidence: float = Field(..., ge=0.0, le=1.0, description="Average block classification confidence")
    page_number_extracted: bool = Field(..., description="Whether a printed page number was found")
    page_region_classified: bool = Field(..., description="Whether page region was classified (front/body/back matter)")

    # Book structure fields (for report generation)
    printed_page_number: Optional[str] = Field(None, description="Printed page number on page")
    numbering_style: Optional[Literal["roman", "arabic", "none"]] = Field(None, description="Page numbering style")
    page_region: Optional[PageRegion] = Field(None, description="Book region classification")

    # Chapter/section structure (for build-structure stage)
    has_chapter_heading: bool = Field(False, description="Does this page contain a CHAPTER_HEADING block?")
    has_section_heading: bool = Field(False, description="Does this page contain a SECTION_HEADING block?")
    chapter_heading_text: Optional[str] = Field(None, description="Text of chapter heading if present (first 100 chars)")
