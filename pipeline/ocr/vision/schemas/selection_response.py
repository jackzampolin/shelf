from typing import Literal
from pydantic import BaseModel, Field


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
