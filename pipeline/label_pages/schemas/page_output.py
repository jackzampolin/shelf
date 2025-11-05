from typing import Optional, Literal
from pydantic import BaseModel, Field

from ..stage1.schemas import StructuralBoundary

PageRegion = Literal["front_matter", "body", "back_matter"]


class LabelPagesPageOutput(BaseModel):
    """Page-level structural metadata for ToC validation.

    Focus: Structural information (page numbers, regions, boundaries)
    not block-level content classification.
    """

    page_number: int = Field(..., ge=1, description="Scan page number")

    # PAGE NUMBER METADATA
    printed_page_number: Optional[str] = Field(
        None,
        description="Printed page number as shown on page (e.g., 'ix', '45', None if unnumbered)"
    )
    numbering_style: Literal["roman", "arabic", "none"] = Field(
        ...,
        description="Style of page numbering detected"
    )
    page_number_location: Literal["header", "footer", "none"] = Field(
        ...,
        description="Where the page number appears on the page"
    )
    page_number_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence in page number extraction"
    )

    # PAGE REGION
    page_region: PageRegion = Field(
        ...,
        description="Book region: front_matter, body, or back_matter"
    )
    page_region_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence in region classification"
    )

    # STRUCTURAL BOUNDARY (descriptive, not hierarchical)
    structural_boundary: StructuralBoundary = Field(
        ...,
        description="Visual and semantic description of structural boundaries"
    )

    # CONTENT FLAGS
    has_table_of_contents: bool = Field(
        ...,
        description="True if this page contains table of contents"
    )

    # METADATA
    model_used: str = Field(..., description="Model used for analysis (e.g., 'gpt-4o')")
    processing_cost: float = Field(..., ge=0.0, description="Cost of processing this page in USD")
    timestamp: str = Field(..., description="ISO timestamp of processing")
