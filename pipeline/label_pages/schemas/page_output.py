"""
Page Output Schema

What we write to disk after labeling.
This is the LLM response + metadata added by the stage.
"""

from typing import List, Optional, Literal
from pydantic import BaseModel, Field

from ..vision.schemas import BlockClassification, PageRegion


class LabelPagesPageOutput(BaseModel):
    """Output from vision-based page number extraction and block classification."""

    # Page identification
    page_number: int = Field(..., ge=1)

    # Book page number extraction (from vision analysis)
    printed_page_number: Optional[str] = Field(
        None,
        description="Book-page number as printed on the image (e.g., 'ix', '45', None if unnumbered)"
    )
    numbering_style: Optional[Literal["roman", "arabic", "none"]] = Field(
        None,
        description="Style of book-page numbering detected"
    )
    page_number_location: Optional[Literal["header", "footer", "none"]] = Field(
        None,
        description="Where the book-page number was found on the image"
    )
    page_number_confidence: float = Field(
        1.0,
        ge=0.0,
        le=1.0,
        description="Confidence in book-page number extraction (1.0 if no number found)"
    )

    # Page region classification
    page_region: Optional[PageRegion] = Field(
        None,
        description="Classified region of book (front/body/back matter, ToC)"
    )
    page_region_confidence: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Confidence in page region classification"
    )

    # Classified blocks
    blocks: List[BlockClassification] = Field(..., description="Block classifications")

    # Processing metadata
    model_used: str = Field(..., description="Model used for labeling (e.g., 'gpt-4o')")
    processing_cost: float = Field(..., ge=0.0, description="Cost of this page in USD")
    timestamp: str = Field(..., description="ISO timestamp of processing")

    # Summary statistics
    total_blocks: int = Field(..., ge=0, description="Total number of blocks classified")
    avg_classification_confidence: float = Field(..., ge=0.0, le=1.0, description="Average block classification confidence")
