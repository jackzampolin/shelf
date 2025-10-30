"""
Vision-based PSM selection schemas.

Pydantic models for structured LLM responses and checkpoint metrics.
"""

from pydantic import BaseModel, Field
from typing import Literal


class VisionSelectionResponse(BaseModel):
    """LLM response for PSM selection."""

    selected_psm: Literal[3, 4, 6] = Field(
        description="Selected PSM mode (3=auto, 4=single column, 6=uniform block)"
    )

    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="LLM confidence in this selection (0.0-1.0)"
    )

    reason: str = Field(
        max_length=500,
        description="Brief explanation of why this PSM is best (structural advantages)"
    )


class VisionSelectionMetrics(BaseModel):
    """Checkpoint metrics for vision selection processing."""

    # Standard LLM metrics
    page_num: int
    processing_time_seconds: float
    cost_usd: float
    attempts: int
    tokens_total: int
    tokens_per_second: float
    model_used: str
    provider: str
    queue_time_seconds: float
    execution_time_seconds: float
    total_time_seconds: float
    ttft_seconds: float
    usage: dict

    # Vision selection specific
    selected_psm: int = Field(description="PSM mode selected by LLM (3, 4, or 6)")
    confidence: float = Field(description="LLM confidence in selection")
    reason: str = Field(description="LLM's explanation for selecting this PSM")
    alternatives_rejected: list[int] = Field(description="PSM modes not selected")
    agreement_similarity: float = Field(description="Similarity score from psm_agreement.json")
    agreement_category: str = Field(description="Agreement category (identical, minor_differences, etc.)")
