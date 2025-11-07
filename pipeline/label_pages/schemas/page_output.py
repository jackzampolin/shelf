from typing import Literal
from pydantic import BaseModel, Field

from ..batch.schemas import VisualSignals, TextualSignals


class LabelPagesPageOutput(BaseModel):
    """Page-level structural boundary detection.

    Focus: Is this page a structural boundary (new chapter/section starts)?
    Uses visual layout and textual flow analysis, NOT header text content.
    """

    page_number: int = Field(..., ge=1, description="Scan page number")

    # BOUNDARY DETECTION
    is_boundary: bool = Field(
        ...,
        description="Is this page a structural boundary (new chapter/section starts)?"
    )

    boundary_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Overall confidence in boundary detection"
    )

    boundary_position: Literal["top", "middle", "bottom", "none"] = Field(
        ...,
        description="Where on the page does the boundary occur? 'none' if not a boundary"
    )

    # SIGNALS (for debugging/verification)
    visual_signals: VisualSignals = Field(
        ...,
        description="Visual indicators from the scanned image"
    )

    textual_signals: TextualSignals = Field(
        ...,
        description="Textual indicators from OCR extraction"
    )

    reasoning: str = Field(
        ...,
        description="Brief explanation focusing on layout and flow, not header content"
    )

    # METADATA
    model_used: str = Field(..., description="Model used for analysis (e.g., 'gpt-4o')")
    processing_cost: float = Field(..., ge=0.0, description="Cost of processing this page in USD")
    timestamp: str = Field(..., description="ISO timestamp of processing")
