from pydantic import BaseModel, Field

from ..batch.schemas import (
    WhitespaceObservation,
    TextContinuationObservation,
    HeadingObservation,
    HeaderObservation,
    FooterObservation,
    OrnamentalBreakObservation,
    FootnotesObservation,
    PageNumberObservation
)


class LabelPagesPageOutput(BaseModel):
    """
    Page structure observations for boundary detection.

    Focus: DESCRIBE what you see, don't INTERPRET what it means.
    These observations will be used downstream for boundary detection.
    """

    scan_page_number: int = Field(..., ge=1, description="Scan page number")

    # Observations organized by logical groups
    # Margins
    header: HeaderObservation
    footer: FooterObservation
    page_number: PageNumberObservation
    # Body structure
    heading: HeadingObservation
    whitespace: WhitespaceObservation
    ornamental_break: OrnamentalBreakObservation
    # Content flow
    text_continuation: TextContinuationObservation
    footnotes: FootnotesObservation

    # METADATA
    model_used: str = Field(..., description="Model used for analysis (e.g., 'gpt-4o')")
    processing_cost: float = Field(..., ge=0.0, description="Cost of processing this page in USD")
    timestamp: str = Field(..., description="ISO timestamp of processing")
