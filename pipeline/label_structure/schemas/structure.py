from pydantic import BaseModel, Field
from typing import Optional, Literal


class HeaderObservation(BaseModel):
    """Header detection (running header in top margin)."""
    present: bool
    text: Optional[str] = Field(default="", description="Header text if present")
    confidence: Literal["high", "medium", "low"]
    source_provider: Literal["mistral", "olm", "paddle"]


class FooterObservation(BaseModel):
    """Footer detection (running footer in bottom margin, NOT footnote content)."""
    present: bool
    text: Optional[str] = Field(default="", description="Footer text if present")
    confidence: Literal["high", "medium", "low"]
    source_provider: Literal["mistral", "olm", "paddle"]


class PageNumberObservation(BaseModel):
    """Page number detection from header/footer."""
    present: bool
    number: Optional[str] = Field(default="", description="Page number value")
    location: Optional[Literal["header", "footer", "margin"]] = None
    confidence: Literal["high", "medium", "low"]
    source_provider: Literal["mistral", "olm", "paddle"]


class StructuralMetadataOutput(BaseModel):
    """Output from Pass 2: LLM structural metadata extraction."""
    header: HeaderObservation
    footer: FooterObservation
    page_number: PageNumberObservation


__all__ = [
    "HeaderObservation",
    "FooterObservation",
    "PageNumberObservation",
    "StructuralMetadataOutput",
]
