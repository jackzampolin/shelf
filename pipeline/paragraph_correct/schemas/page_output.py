from typing import List
from pydantic import BaseModel, Field

from ..vision.schemas import BlockCorrection

class ParagraphCorrectPageOutput(BaseModel):

    page_number: int = Field(..., ge=1)

    blocks: List[BlockCorrection] = Field(..., description="Block corrections")

    model_used: str = Field(..., description="Model used for correction (e.g., 'gpt-4o')")
    processing_cost: float = Field(..., ge=0.0, description="Cost of this page in USD")
    timestamp: str = Field(..., description="ISO timestamp of processing")

    total_blocks: int = Field(..., ge=0, description="Total number of blocks corrected")
    total_corrections: int = Field(..., ge=0, description="Total number of paragraphs corrected")
    avg_confidence: float = Field(..., ge=0.0, le=1.0, description="Average text confidence")
