"""
OCRv2 schemas - reuses OCR output schema for compatibility,
with custom metrics for provider-based processing.
"""

from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, Field

# Re-export OCR output schema (identical output format)
from .ocr_page_schemas import OCRPageOutput, OCRPageReport


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


class ProviderOutput(BaseModel):
    """
    Provider output data structure used during selection.

    Returned by _load_provider_outputs() for comparing provider results.
    """
    text: str = Field(..., description="Extracted text from this provider")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Average confidence score")
    data: Dict[str, Any] = Field(..., description="Full OCR output (OCRPageOutput format)")


class VisionSelectionResponse(BaseModel):
    """
    LLM response from vision-based provider selection.

    Used when provider agreement < 0.95 to choose best OCR output.
    """
    selected_provider: str = Field(..., description="Chosen provider name")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in selection (0.0-1.0)")
    reasoning: str = Field(..., description="Explanation for selection decision")


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


__all__ = [
    "OCRPageOutput",
    "OCRPageMetrics",
    "OCRPageReport",
    "ProviderSelection",
    "ProviderOutput",
    "VisionSelectionResponse",
]
