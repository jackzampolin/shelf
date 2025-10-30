"""Vision selection response schema."""

from pydantic import BaseModel, Field


class VisionSelectionResponse(BaseModel):
    """
    LLM response from vision-based provider selection.

    Used when provider agreement < 0.95 to choose best OCR output.
    """
    selected_provider: str = Field(..., description="Chosen provider name")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in selection (0.0-1.0)")
    reasoning: str = Field(..., description="Explanation for selection decision")
