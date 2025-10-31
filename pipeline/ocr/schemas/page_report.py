from pydantic import BaseModel, Field


class OCRPageReport(BaseModel):
    page_num: int = Field(..., ge=1, description="Page number")
    confidence_mean: float = Field(..., ge=0.0, le=1.0, description="Mean OCR confidence (low = poor quality)")
    blocks_detected: int = Field(..., ge=0, description="Text blocks detected (abnormal values = layout issues)")
