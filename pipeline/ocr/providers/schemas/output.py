from typing import Dict, Any
from pydantic import BaseModel, Field


class ProviderOutput(BaseModel):
    text: str = Field(..., description="Extracted text from this provider")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Average confidence score")
    data: Dict[str, Any] = Field(..., description="Full OCR output (OCRPageOutput format)")
