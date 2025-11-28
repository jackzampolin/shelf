from pydantic import BaseModel, Field
from typing import List, Literal, Optional
from .structure import HeaderObservation, FooterObservation, PageNumberObservation
from .annotations import ReferenceMarker, FootnoteContent, CrossReference


class UnifiedExtractionOutput(BaseModel):
    """Combined output from unified structure + annotations extraction.

    Replaces separate StructuralMetadataOutput and AnnotationsOutput with
    a single LLM call that extracts both in one pass.
    """

    # Structure fields (from Phase 2)
    header: HeaderObservation
    footer: FooterObservation
    page_number: PageNumberObservation

    # Annotation fields (from Phase 3)
    markers_present: bool = Field(..., description="Any reference markers found in body text?")
    markers: List[ReferenceMarker] = Field(
        default_factory=list,
        description="All reference markers found (footnote/endnote/citation markers)"
    )

    footnotes_present: bool = Field(..., description="Footnote content at bottom of page?")
    footnotes: List[FootnoteContent] = Field(
        default_factory=list,
        description="Footnote content found at bottom of this specific page"
    )

    cross_references_present: bool = Field(..., description="Internal links/cross-refs found?")
    cross_references: List[CrossReference] = Field(
        default_factory=list,
        description="Internal document links (e.g., 'see Chapter 3')"
    )

    has_horizontal_rule: bool = Field(
        False,
        description="Horizontal line separating body text from footnotes?"
    )
    has_small_text_at_bottom: bool = Field(
        False,
        description="Visually smaller text at bottom (footnote indicator)?"
    )

    confidence: Literal["high", "medium", "low"]


__all__ = [
    "UnifiedExtractionOutput",
]
