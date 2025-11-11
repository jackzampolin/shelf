"""
LLM response schema for structure extraction.

This is what the LLM returns - we use OpenRouter's structured outputs.
"""

from pydantic import BaseModel, Field
from typing import Optional, Literal, List


class LLMHeaderObservation(BaseModel):
    """Header observation from LLM."""
    present: bool
    text: Optional[str]
    confidence: Literal["high", "medium", "low"]
    source_provider: Literal["mistral", "olm", "paddle"]


class LLMFooterObservation(BaseModel):
    """Footer observation from LLM."""
    present: bool
    text: Optional[str]
    confidence: Literal["high", "medium", "low"]
    source_provider: Literal["mistral", "olm", "paddle"]


class LLMPageNumberObservation(BaseModel):
    """Page number observation from LLM."""
    present: bool
    number: Optional[str]
    location: Optional[Literal["header", "footer", "margin"]]
    confidence: Literal["high", "medium", "low"]
    source_provider: Literal["mistral", "olm", "paddle"]


class LLMHeadingItem(BaseModel):
    """Individual heading item."""
    level: int = Field(..., ge=1, le=6)
    text: str


class LLMHeadingObservation(BaseModel):
    """Heading observations from LLM."""
    present: bool
    headings: List[LLMHeadingItem] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"]
    source_provider: Literal["mistral", "olm", "paddle"]


class StructureExtractionResponse(BaseModel):
    """
    LLM response schema for structure extraction.

    This is passed to OpenRouter as response_format to get structured output.
    """
    header: LLMHeaderObservation
    footer: LLMFooterObservation
    page_number: LLMPageNumberObservation
    headings: LLMHeadingObservation
