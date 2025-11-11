"""
Structural observation schemas for page metadata extraction.

These schemas capture the structural elements of a page:
- Margins (headers, footers, page numbers)
- Body structure (headings)

This is what label-pages SHOULD have been doing all along.
"""

from pydantic import BaseModel, Field
from typing import Optional, Literal


class HeaderObservation(BaseModel):
    """Observation about page header."""
    present: bool = Field(..., description="Whether a header is present")
    text: Optional[str] = Field(None, description="Header text if present")
    confidence: Literal["high", "medium", "low"] = Field(..., description="Confidence in observation")
    source_provider: str = Field(..., description="Which OCR provider detected this (mistral/olm/paddle)")


class FooterObservation(BaseModel):
    """Observation about page footer."""
    present: bool = Field(..., description="Whether a footer is present")
    text: Optional[str] = Field(None, description="Footer text if present")
    confidence: Literal["high", "medium", "low"] = Field(..., description="Confidence in observation")
    source_provider: str = Field(..., description="Which OCR provider detected this")


class PageNumberObservation(BaseModel):
    """Observation about page number."""
    present: bool = Field(..., description="Whether a page number is present")
    number: Optional[str] = Field(None, description="Page number if detected")
    location: Optional[Literal["header", "footer", "margin"]] = Field(None, description="Where page number appears")
    confidence: Literal["high", "medium", "low"] = Field(..., description="Confidence in observation")
    source_provider: str = Field(..., description="Which OCR provider detected this")


class HeadingObservation(BaseModel):
    """Observation about headings on the page."""
    present: bool = Field(..., description="Whether headings are present")
    headings: list[dict] = Field(
        default_factory=list,
        description="List of detected headings with {level: int, text: str}"
    )
    confidence: Literal["high", "medium", "low"] = Field(..., description="Confidence in observation")
    source_provider: str = Field(..., description="Which OCR provider detected this (usually mistral)")
