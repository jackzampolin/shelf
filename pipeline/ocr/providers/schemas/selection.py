from typing import Optional, Literal
from pydantic import BaseModel, Field


class ProviderSelection(BaseModel):
    provider: str = Field(..., description="Selected provider name (e.g., 'tesseract-psm4')")
    method: Literal["automatic", "vision"] = Field(..., description="Selection method")
    agreement: float = Field(..., ge=0.0, le=1.0, description="Provider agreement score")
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0, description="Confidence in selection (vision only)")
