from typing import List, Optional, Literal
from pydantic import BaseModel, Field

from .page_region import PageRegion
from .block_classification import BlockClassification


class LabelLLMResponse(BaseModel):
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

    blocks: List[BlockClassification] = Field(..., description="Block classifications")
