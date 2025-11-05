"""
Stage 1 LLM Response Schema

Simplified: Focus on structural boundary detection using vision + OCR text.
"""

from typing import Optional, Literal
from pydantic import BaseModel, Field


class VisualSignals(BaseModel):
    """Visual indicators from the scanned image."""

    whitespace_amount: Literal["minimal", "moderate", "extensive"] = Field(
        ...,
        description="Amount of empty space on page"
    )

    heading_size: Literal["none", "small", "medium", "large", "very_large"] = Field(
        ...,
        description="Heading size relative to body text"
    )

    heading_visible: bool = Field(
        ...,
        description="Is a distinct heading visible in the content area?"
    )


class TextualSignals(BaseModel):
    """Textual indicators from OCR extraction."""

    starts_with_heading: bool = Field(
        ...,
        description="Does the OCR text start with a heading?"
    )

    appears_to_continue: bool = Field(
        ...,
        description="Does the text appear to continue from a previous page?"
    )

    first_line_preview: str = Field(
        ...,
        max_length=100,
        description="First ~50 characters of OCR text for verification"
    )


class HeadingInfo(BaseModel):
    """Information about the heading if this is a boundary page."""

    heading_text: Optional[str] = Field(
        None,
        description="Extracted heading text (e.g., 'Chapter Five', 'Part II: The War Years')"
    )

    heading_style: str = Field(
        ...,
        description="Visual styling: position, typography, formatting"
    )

    suggested_type: str = Field(
        ...,
        description="Semantic type: 'chapter', 'part', 'section', 'prologue', 'epilogue', 'appendix', 'preface', 'unknown'"
    )

    type_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence in the type classification"
    )


class Stage1LLMResponse(BaseModel):
    """
    Simplified structural boundary detection.

    Focus: Is this page a structural boundary (chapter/part/section start)?
    Uses both visual signals (from image) and textual signals (from OCR).
    """

    is_boundary: bool = Field(
        ...,
        description="Is this page a structural boundary?"
    )

    boundary_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Overall confidence in boundary detection"
    )

    visual_signals: VisualSignals = Field(
        ...,
        description="Visual indicators from the image"
    )

    textual_signals: TextualSignals = Field(
        ...,
        description="Textual indicators from OCR"
    )

    heading_info: Optional[HeadingInfo] = Field(
        None,
        description="Heading information if is_boundary=true"
    )

    reasoning: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Brief explanation of the decision (1-2 sentences)"
    )
