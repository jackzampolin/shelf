"""
Page Output Schema

What we write to disk after correction.
This is the LLM response + metadata added by the stage.
"""

from typing import List
from pydantic import BaseModel, Field

from ..vision.schemas import BlockCorrection


class ParagraphCorrectPageOutput(BaseModel):
    """Output from vision-based correction of a single page."""

    # Page identification
    page_number: int = Field(..., ge=1)

    # Corrected blocks (no classification or page number extraction)
    blocks: List[BlockCorrection] = Field(..., description="Block corrections")

    # Processing metadata
    model_used: str = Field(..., description="Model used for correction (e.g., 'gpt-4o')")
    processing_cost: float = Field(..., ge=0.0, description="Cost of this page in USD")
    timestamp: str = Field(..., description="ISO timestamp of processing")

    # Summary statistics
    total_blocks: int = Field(..., ge=0, description="Total number of blocks corrected")
    total_corrections: int = Field(..., ge=0, description="Total number of paragraphs corrected")
    avg_confidence: float = Field(..., ge=0.0, le=1.0, description="Average text confidence")
