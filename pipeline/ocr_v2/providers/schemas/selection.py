"""Provider selection schema."""

from typing import Optional, Literal
from pydantic import BaseModel, Field


class ProviderSelection(BaseModel):
    """
    Selection map entry tracking which provider was chosen for a page.

    Written to selection_map.json incrementally during provider selection.
    Maps page_num (as string key) -> ProviderSelection.
    """
    provider: str = Field(..., description="Selected provider name (e.g., 'tesseract-psm4')")
    method: Literal["automatic", "vision"] = Field(..., description="Selection method")
    agreement: float = Field(..., ge=0.0, le=1.0, description="Provider agreement score")
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0, description="Confidence in selection (vision only)")
