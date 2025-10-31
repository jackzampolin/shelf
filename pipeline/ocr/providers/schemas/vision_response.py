from pydantic import BaseModel, Field


class VisionSelectionResponse(BaseModel):
    selected_provider: str = Field(..., description="Chosen provider name")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in selection (0.0-1.0)")
    reasoning: str = Field(..., description="Explanation for selection decision")
