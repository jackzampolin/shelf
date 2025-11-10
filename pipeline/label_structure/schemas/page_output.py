"""
Final merged output schema for label-structure stage.

Combines margin + body + content observations into single output.
Compatible with label-pages schema for downstream stages.
"""

from pydantic import BaseModel, Field

from ..margin.schemas import (
    HeaderObservation,
    FooterObservation,
    PageNumberObservation
)
from ..body.schemas import (
    HeadingObservation,
    WhitespaceObservation,
    OrnamentalBreakObservation
)
from ..content.schemas import (
    TextContinuationObservation,
    FootnotesObservation
)


class LabelStructurePageOutput(BaseModel):
    """
    Merged page structure observations from three-pass analysis.

    Combines:
    - Pass 1 (Margin): header, footer, page_number
    - Pass 2 (Body): heading, whitespace, ornamental_break
    - Pass 3 (Content): text_continuation, footnotes

    Schema matches label-pages for downstream compatibility.
    """

    scan_page_number: int = Field(..., ge=1, description="Scan page number")

    # Observations organized by logical groups
    # Margins (from pass 1)
    header: HeaderObservation
    footer: FooterObservation
    page_number: PageNumberObservation
    # Body structure (from pass 2)
    heading: HeadingObservation
    whitespace: WhitespaceObservation
    ornamental_break: OrnamentalBreakObservation
    # Content flow (from pass 3)
    text_continuation: TextContinuationObservation
    footnotes: FootnotesObservation

    # METADATA
    model_used: str = Field(..., description="Model used for analysis (e.g., 'gpt-4o')")
    processing_cost: float = Field(..., ge=0.0, description="Total cost across all 3 passes in USD")
    timestamp: str = Field(..., description="ISO timestamp of final merge")
