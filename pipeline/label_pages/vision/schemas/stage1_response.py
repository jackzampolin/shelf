"""
Stage 1 LLM Response Schema

Captures high-level structural observations from 3-image vision call.
"""

from typing import Optional, Literal
from pydantic import BaseModel, Field


class StructuralBoundary(BaseModel):
    """Detects if page is a chapter/part boundary."""
    is_boundary: bool = Field(..., description="True if this is a chapter/part start page")
    boundary_type: Optional[Literal["part_start", "chapter_start"]] = Field(
        None, description="Type of boundary (null if not a boundary)"
    )
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in boundary detection")
    reasoning: str = Field(..., min_length=1, description="Brief explanation of decision")


class SequenceValidation(BaseModel):
    """Page number sequence validation using adjacent pages."""
    prev_number: Optional[str] = Field(None, description="Page number from previous page")
    next_number: Optional[str] = Field(None, description="Page number from next page")
    sequence_valid: bool = Field(..., description="Does current fit sequence between prev/next?")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in sequence validation")


class PageNumber(BaseModel):
    """Printed page number extraction with sequence validation."""
    printed_number: Optional[str] = Field(None, description="Printed page number (e.g., '42', 'ix', null)")
    numbering_style: Literal["roman", "arabic", "none"] = Field(..., description="Numbering style detected")
    location: Literal["header", "footer", "none"] = Field(..., description="Where page number appears")
    sequence_validation: SequenceValidation = Field(..., description="Validation using adjacent pages")


class PageRegionInfo(BaseModel):
    """Page region classification."""
    region: Literal["front_matter", "body", "back_matter"] = Field(..., description="Book region")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in region classification")
    reasoning: str = Field(..., min_length=1, description="Brief explanation of classification")


class Stage1LLMResponse(BaseModel):
    """
    Stage 1 output: High-level structural analysis using 3-image context.

    This schema captures observations that benefit from seeing adjacent pages:
    - Structural boundaries (chapter/part starts with whitespace/typography changes)
    - Page number sequences (validation and transition detection)
    - Region classification (front_matter/body/back_matter transitions)

    The key insight: Understanding the current page through comparison with neighbors.
    """

    structural_boundary: StructuralBoundary = Field(..., description="Chapter/part boundary detection")
    page_number: PageNumber = Field(..., description="Printed page number with sequence validation")
    page_region: PageRegionInfo = Field(..., description="Book region classification")
