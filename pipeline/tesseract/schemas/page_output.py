from typing import List
from pydantic import BaseModel, Field

from .paragraph import TesseractParagraph


class TesseractPageOutput(BaseModel):
    """Output schema for Tesseract OCR processing (paragraph-level only)."""
    page_num: int = Field(..., ge=1, description="Page number in book")
    paragraphs: List[TesseractParagraph] = Field(
        default_factory=list,
        description="Paragraphs detected by Tesseract"
    )
    avg_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Average confidence across all paragraphs"
    )
    processing_time_seconds: float = Field(
        ...,
        ge=0.0,
        description="Time taken to process this page"
    )
