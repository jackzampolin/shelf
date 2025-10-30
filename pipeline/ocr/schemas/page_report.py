"""OCR page quality report schema."""

from pydantic import BaseModel, Field


class OCRPageReport(BaseModel):
    """
    Quality-focused report for OCR stage.

    Minimal report to spot low-quality OCR pages.
    LLMs consume OCR directly, so just flag potential issues.
    """
    page_num: int = Field(..., ge=1, description="Page number")
    confidence_mean: float = Field(..., ge=0.0, le=1.0, description="Mean OCR confidence (low = poor quality)")
    blocks_detected: int = Field(..., ge=0, description="Text blocks detected (abnormal values = layout issues)")
