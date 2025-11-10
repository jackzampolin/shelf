"""
Observation-based page structure schema for label-pages.

Key principle: Describe what you SEE, not what it MEANS.
Separate observation from interpretation.
"""

from typing import Literal, Optional, List
from pydantic import BaseModel, Field


class WhitespaceObservation(BaseModel):
    """Observations about whitespace on the page."""

    zones: List[Literal["top", "middle", "bottom"]] = Field(
        default_factory=list,
        description="Where is significant whitespace visible? Can be multiple zones. Empty list if no whitespace."
    )

    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence in whitespace observation (0.0-1.0)"
    )


class TextContinuationObservation(BaseModel):
    """Observations about text flow across page boundaries."""

    from_previous: bool = Field(
        ...,
        description="Does text appear to continue from previous page? (starts mid-sentence, mid-paragraph)"
    )

    to_next: bool = Field(
        ...,
        description="Does text appear to continue to next page? (ends mid-sentence, no concluding punctuation)"
    )

    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence in continuation observation (0.0-1.0)"
    )


class HeaderObservation(BaseModel):
    """Observations about headers in margin areas (running headers)."""

    exists: bool = Field(
        ...,
        description="Is there a header in the top margin area?"
    )

    text: Optional[str] = Field(
        None,
        max_length=200,
        description="The header text if visible (null if no header)"
    )

    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence in header observation (0.0-1.0)"
    )


class HeadingObservation(BaseModel):
    """Observations about headings/titles in body area (chapter/section markers)."""

    exists: bool = Field(
        ...,
        description="Is there a large/decorative heading in the body area?"
    )

    text: Optional[str] = Field(
        None,
        max_length=500,
        description="The heading text if visible (null if no heading)"
    )

    position: Optional[Literal["top", "middle", "bottom"]] = Field(
        None,
        description="Where is the heading located? (null if no heading)"
    )

    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence in heading observation (0.0-1.0)"
    )


class FooterObservation(BaseModel):
    """Observations about footers on the page."""

    exists: bool = Field(
        ...,
        description="Is there a footer visible?"
    )

    text: Optional[str] = Field(
        None,
        max_length=200,
        description="The footer text if visible (null if no footer)"
    )

    position: Optional[Literal["left", "center", "right"]] = Field(
        None,
        description="Where is the footer located? (null if no footer)"
    )

    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence in footer observation (0.0-1.0)"
    )


class OrnamentalBreakObservation(BaseModel):
    """Observations about ornamental/visual breaks on the page."""

    exists: bool = Field(
        ...,
        description="Is there a visual break? (asterisks, rules, symbols, significant whitespace)"
    )

    position: Optional[Literal["top", "middle", "bottom"]] = Field(
        None,
        description="Where is the break located? (null if no break)"
    )

    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence in ornamental break observation (0.0-1.0)"
    )


class FootnotesObservation(BaseModel):
    """Observations about footnotes on the page."""

    exists: bool = Field(
        ...,
        description="Are there footnotes visible? (small text at bottom, references)"
    )

    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence in footnote observation (0.0-1.0)"
    )


class PageNumberObservation(BaseModel):
    """Observations about page numbering."""

    exists: bool = Field(
        ...,
        description="Is there a page number visible?"
    )

    number: Optional[str] = Field(
        None,
        max_length=20,
        description="The page number as shown (e.g., '15', 'xiv', '3-12') (null if none)"
    )

    position: Optional[Literal["top_center", "top_outer", "top_inner", "bottom_center", "bottom_outer", "bottom_inner"]] = Field(
        None,
        description="Where is the page number located? (null if none)"
    )

    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence in page number observation (0.0-1.0)"
    )


class PageStructureObservation(BaseModel):
    """
    Complete structural observations for a single page.

    Focus: DESCRIBE what you see, don't INTERPRET what it means.
    These observations will be used downstream for boundary detection.
    """

    # Observations organized by logical groups
    # Margins
    header: HeaderObservation
    footer: FooterObservation
    page_number: PageNumberObservation
    # Body structure
    heading: HeadingObservation
    whitespace: WhitespaceObservation
    ornamental_break: OrnamentalBreakObservation
    # Content flow
    text_continuation: TextContinuationObservation
    footnotes: FootnotesObservation
