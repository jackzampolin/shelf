"""OCR page metrics schema for checkpoint tracking."""

from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class OCRPageMetrics(BaseModel):
    """
    Checkpoint metrics for OCRv2 stage.

    Flat provider list approach - tracks which providers completed,
    and which was ultimately selected.
    """

    page_num: int = Field(..., ge=1, description="Page number processed")

    # Provider completion tracking
    providers_complete: List[str] = Field(
        default_factory=list,
        description="List of providers that completed (e.g., ['tesseract-psm3', 'tesseract-psm4'])"
    )

    # Selection tracking
    selected_provider: Optional[str] = Field(
        None,
        description="Selected provider name (e.g., 'tesseract-psm4')"
    )
    selection_method: Literal["pending", "automatic", "vision"] = Field(
        "pending",
        description="How provider was selected: automatic (high agreement), vision (LLM), or pending"
    )

    # Agreement metrics
    provider_agreement: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Text similarity across providers (0.0-1.0)"
    )

    # Vision selection metadata (if used)
    cost_usd: float = Field(0.0, ge=0.0, description="Cost (vision LLM if used)")
    confidence: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Vision confidence in selection (if vision used)"
    )
    reason: Optional[str] = Field(None, description="Vision selection reasoning (if vision used)")

    # Quality metrics
    blocks_detected: int = Field(0, ge=0, description="Number of blocks in selected output")
    processing_time_seconds: float = Field(0.0, ge=0.0, description="Total processing time")
