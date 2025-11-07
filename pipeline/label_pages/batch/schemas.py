"""
Stage 1 LLM Response Schema

Focus: Detect structural boundaries (new chapters/sections) vs continuation pages.
"""

from typing import Literal
from pydantic import BaseModel, Field


class VisualSignals(BaseModel):
    """Visual indicators from the scanned image."""

    whitespace_amount: Literal["minimal", "moderate", "extensive"] = Field(
        ...,
        description="Amount of empty space at the top of the page"
    )

    page_density: Literal["sparse", "moderate", "dense"] = Field(
        ...,
        description="Overall density of content on the page"
    )


class TextualSignals(BaseModel):
    """Textual indicators from OCR extraction."""

    starts_mid_sentence: bool = Field(
        ...,
        description="Does the OCR text start mid-sentence (clear continuation)?"
    )

    appears_to_continue: bool = Field(
        ...,
        description="Does the text appear to continue from a previous page?"
    )

    has_boundary_marker: bool = Field(
        ...,
        description="Is there a chapter/section number or marker visible (arabic/roman numerals, letters)?"
    )

    boundary_marker_text: str = Field(
        default="",
        max_length=600,
        description="The actual marker text if present (e.g. 'Chapter 5', 'II', '3', 'Part A')"
    )


class Stage1LLMResponse(BaseModel):
    """
    Structural boundary detection without header confusion.

    Focus: Is this page a structural boundary (new chapter/section starts here)?
    Uses visual layout and textual flow, NOT header text content.
    """

    is_boundary: bool = Field(
        ...,
        description="Is this page a structural boundary (new chapter/section starts here)?"
    )

    boundary_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Overall confidence in boundary detection"
    )

    boundary_position: Literal["top", "middle", "bottom", "none"] = Field(
        ...,
        description="Where on the page does the boundary occur? 'none' if not a boundary"
    )

    visual_signals: VisualSignals = Field(
        ...,
        description="Visual indicators from the image"
    )

    textual_signals: TextualSignals = Field(
        ...,
        description="Textual indicators from OCR"
    )

    reasoning: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Brief explanation focusing on layout and flow, not header content (1-2 sentences)"
    )
