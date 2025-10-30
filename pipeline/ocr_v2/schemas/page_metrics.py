"""OCR page checkpoint metrics schema."""

from pydantic import BaseModel, Field


class OCRPageMetrics(BaseModel):
    """
    Checkpoint metrics for OCR stage.

    Tracks Tesseract OCR performance per page per PSM mode.
    OCR stage is unique - no LLM costs for pages, but tracks
    OCR quality metrics (confidence, blocks detected).
    """
    page_num: int = Field(..., ge=1, description="Page number processed")
    processing_time_seconds: float = Field(..., ge=0.0, description="Tesseract processing time")
    cost_usd: float = Field(0.0, ge=0.0, description="Cost (always 0 for Tesseract)")

    # OCR-specific metrics
    psm_mode: int = Field(..., ge=0, le=13, description="Tesseract PSM mode used")
    tesseract_version: str = Field(..., description="Tesseract version used")
    confidence_mean: float = Field(..., ge=0.0, le=1.0, description="Mean OCR confidence across page")
    blocks_detected: int = Field(..., ge=0, description="Number of text blocks detected")
    recovered_text_blocks_count: int = Field(0, ge=0, description="Number of text blocks recovered from image validation")
