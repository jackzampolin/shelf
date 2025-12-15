from typing import List, Optional
from pydantic import BaseModel, Field


class TextCorrection(BaseModel):
    """A single text correction to apply to the base OCR output."""
    original: str = Field(..., description="Exact text to find in the base output")
    replacement: str = Field(..., description="Corrected text to replace it with")
    reason: str = Field(..., description="Brief explanation (OCR error, missing word, etc.)")


class BlendCorrections(BaseModel):
    """All corrections for a page, returned by the LLM."""
    corrections: List[TextCorrection] = Field(
        default_factory=list,
        description="List of text corrections to apply"
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence in the corrections (0.0-1.0)"
    )


class BlendedOcrPageOutput(BaseModel):
    """Final blended OCR output for a page."""
    markdown: str = Field(...)
    model_used: str = Field(...)
    base_source: str = Field(default="mistral", description="Which OCR output was used as base")
    corrections_applied: int = Field(default=0, ge=0, description="Number of corrections applied")
    corrections: List[TextCorrection] = Field(default_factory=list, description="Corrections suggested by LLM")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="LLM confidence in corrections")
