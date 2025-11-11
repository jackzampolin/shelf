from pydantic import BaseModel, Field

from .observations import (
    HeaderObservation,
    FooterObservation,
    PageNumberObservation,
    HeadingObservation,
)


class LabelStructurePageOutput(BaseModel):
    """
    Structural metadata extracted by LLM from multiple OCR providers.

    This stage extracts the structural elements that downstream stages need:
    - Page margins (headers, footers, page numbers)
    - Body structure (headings)

    This is what label-pages SHOULD have been doing all along.
    """

    page_num: int = Field(..., ge=1, description="Page number in book")

    # MARGINS - Critical structural metadata
    header: HeaderObservation = Field(..., description="Header observation")
    footer: FooterObservation = Field(..., description="Footer observation")
    page_number: PageNumberObservation = Field(..., description="Page number observation")

    # BODY STRUCTURE
    headings: HeadingObservation = Field(..., description="Heading observations")
