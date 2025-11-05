from typing import Optional
from pydantic import BaseModel, Field

from ..stage1.schemas import VisualSignals, TextualSignals, HeadingInfo


class LabelPagesPageOutput(BaseModel):
    """Simplified page-level structural metadata.

    Focus: Is this page a structural boundary (chapter/part/section start)?
    Uses vision + OCR text for accurate detection.
    """

    page_number: int = Field(..., ge=1, description="Scan page number")

    # BOUNDARY DETECTION (simplified)
    is_boundary: bool = Field(
        ...,
        description="Is this page a structural boundary (chapter/part/section start)?"
    )

    boundary_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Overall confidence in boundary detection"
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

    # HEADING INFO (if boundary detected)
    heading_info: Optional[HeadingInfo] = Field(
        None,
        description="Heading information if is_boundary=true"
    )

    reasoning: str = Field(
        ...,
        description="Brief explanation of the boundary detection decision"
    )

    # METADATA
    model_used: str = Field(..., description="Model used for analysis (e.g., 'gpt-4o')")
    processing_cost: float = Field(..., ge=0.0, description="Cost of processing this page in USD")
    timestamp: str = Field(..., description="ISO timestamp of processing")
