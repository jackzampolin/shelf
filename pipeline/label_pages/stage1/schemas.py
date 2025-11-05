"""
Stage 1 LLM Response Schema

Captures high-level structural observations from 3-image vision call.
Focus: Describe what you see, don't classify hierarchy.
"""

from typing import Optional, Literal
from pydantic import BaseModel, Field


class StructuralBoundary(BaseModel):
    """Describes visual characteristics of a structural boundary.

    Philosophy: Describe what you SEE (whitespace, heading size, style)
    rather than classifying hierarchy (which needs full book context).
    """
    is_boundary: bool = Field(
        ...,
        description="True if this page is a structural boundary (chapter/part/section start)"
    )

    whitespace_amount: Literal["minimal", "moderate", "extensive"] = Field(
        ...,
        description="Amount of empty space on page: minimal (<30%), moderate (30-60%), extensive (>60%)"
    )

    heading_size: Literal["none", "small", "medium", "large", "very_large"] = Field(
        ...,
        description="Heading size relative to body text: none, small (~1x), medium (~1.5x), large (~2x), very_large (>2x)"
    )

    heading_style: Optional[str] = Field(
        None,
        description="Visual style of heading: 'centered', 'left-aligned', 'decorative', 'numbered', 'uppercase', etc."
    )

    suggested_type: Optional[str] = Field(
        None,
        description="Best guess at semantic type from text: 'part', 'chapter', 'section', 'appendix', 'preface', etc."
    )

    suggested_type_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence in suggested_type (based on text hints like 'Part I', 'Chapter 5')"
    )

    boundary_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Overall confidence that this IS a boundary"
    )

    reasoning: str = Field(
        ...,
        min_length=1,
        description="Brief explanation of visual observations"
    )


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
    - Structural boundaries (describe visual characteristics, not hierarchy)
    - Page number sequences (validation and transition detection)
    - Region classification (front_matter/body/back_matter transitions)
    - Content flags (ToC detection)

    Philosophy: Describe what you SEE, let downstream tasks infer structure.
    """

    structural_boundary: StructuralBoundary = Field(..., description="Visual description of structural boundaries")
    page_number: PageNumber = Field(..., description="Printed page number with sequence validation")
    page_region: PageRegionInfo = Field(..., description="Book region classification")
    has_table_of_contents: bool = Field(..., description="True if this page contains table of contents")
