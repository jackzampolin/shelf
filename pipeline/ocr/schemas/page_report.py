from typing import Optional, Literal
from pydantic import BaseModel, Field


class OCRPageReport(BaseModel):
    page_num: int = Field(..., ge=1, description="Page number")

    selected_provider: str = Field(..., description="Selected provider name (e.g., tesseract-psm3)")
    selection_method: Literal["automatic", "vision"] = Field(..., description="How provider was selected")

    provider_agreement: float = Field(..., ge=0.0, le=1.0, description="Text similarity between providers (< 0.95 = vision tie-break)")

    confidence_mean: float = Field(..., ge=0.0, le=1.0, description="OCR or vision LLM confidence")

    blocks_detected: int = Field(..., ge=0, description="Text blocks detected (abnormal values = layout issues)")

    vision_reason: Optional[str] = Field(None, description="Vision LLM selection reason")
    vision_cost_usd: Optional[float] = Field(None, ge=0.0, description="Vision LLM cost in USD")
