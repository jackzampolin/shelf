"""
Content flow schema - Pass 3 of label-structure.

Focus: Text continuation and footnotes (text-based analysis).
Uses: OCR text + margin + body output for context.
No vision needed - pure text analysis.
"""

from pydantic import BaseModel, Field


class TextContinuationObservation(BaseModel):
    """Text flow across page boundaries."""

    from_previous: bool = Field(
        ...,
        description="Does text continue from previous page? (starts mid-sentence, mid-paragraph)"
    )

    to_next: bool = Field(
        ...,
        description="Does text continue to next page? (ends mid-sentence, no concluding punctuation)"
    )

    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence in continuation observation (0.0-1.0)"
    )


class FootnotesObservation(BaseModel):
    """Footnotes presence on the page."""

    exists: bool = Field(
        ...,
        description="Are there footnotes present? (reference markers like ¹, ², *, †)"
    )

    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence in footnote observation (0.0-1.0)"
    )


class ContentObservation(BaseModel):
    """
    Content flow observation - Pass 3 of label-structure.

    Analyzes text content for:
    - Text continuation (flow across pages)
    - Footnotes (reference markers)

    Uses OCR text + margin + body context.
    No vision needed - text-only analysis.
    """

    text_continuation: TextContinuationObservation
    footnotes: FootnotesObservation

    # Reasoning
    reasoning: str = Field(
        ...,
        max_length=500,
        description="Brief explanation of observations and confidence levels"
    )
