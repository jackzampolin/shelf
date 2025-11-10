"""
Body structure schema - Pass 2 of label-structure.

Focus: Identify body layout elements (heading, whitespace, ornamental breaks).
Uses: Image + margin pass output for context.
"""

from typing import Literal, Optional, List
from pydantic import BaseModel, Field


class HeadingObservation(BaseModel):
    """Chapter/section heading in body area."""

    exists: bool = Field(
        ...,
        description="Is there a large/decorative heading in the body area?"
    )

    text: Optional[str] = Field(
        None,
        max_length=500,
        description="Heading text if visible (null if no heading)"
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


class WhitespaceObservation(BaseModel):
    """Significant whitespace/blank areas on page."""

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


class OrnamentalBreakObservation(BaseModel):
    """Visual breaks/separators on the page."""

    exists: bool = Field(
        ...,
        description="Is there a visual break? (asterisks, rules, symbols, deliberate whitespace separator)"
    )

    type: Optional[Literal["symbols", "rule", "whitespace"]] = Field(
        None,
        description="Type of ornamental break (null if none)"
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


class BodyObservation(BaseModel):
    """
    Body structure observation - Pass 2 of label-structure.

    Observes visual layout of body area:
    - Heading (chapter/section titles)
    - Whitespace (blank areas)
    - Ornamental breaks (visual separators)

    Has access to margin pass output for context.
    """

    heading: HeadingObservation
    whitespace: WhitespaceObservation
    ornamental_break: OrnamentalBreakObservation

    # Reasoning
    reasoning: str = Field(
        ...,
        max_length=500,
        description="Brief explanation of observations and confidence levels"
    )
