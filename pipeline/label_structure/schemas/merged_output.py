from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from .mechanical import HeadingItem, PatternHints
from .structure import HeaderObservation, FooterObservation, PageNumberObservation
from .annotations import ReferenceMarker, FootnoteContent, CrossReference


class LabelStructurePageOutput(BaseModel):
    headings_present: bool = Field(..., description="Any headings found?")
    headings: List[HeadingItem] = Field(default_factory=list, description="Extracted headings")
    pattern_hints: PatternHints = Field(
        default_factory=PatternHints,
        description="Mechanically detected pattern hints (footnotes, endnotes, charts)"
    )

    header: HeaderObservation
    footer: FooterObservation
    page_number: PageNumberObservation

    markers_present: bool = Field(..., description="Reference markers in body text?")
    markers: List[ReferenceMarker] = Field(default_factory=list)

    footnotes_present: bool = Field(..., description="Footnote content at bottom?")
    footnotes: List[FootnoteContent] = Field(default_factory=list)

    cross_references_present: bool = Field(..., description="Internal links?")
    cross_references: List[CrossReference] = Field(default_factory=list)

    has_horizontal_rule: bool = Field(False, description="Separator line before footnotes?")
    has_small_text_at_bottom: bool = Field(False, description="Small text at bottom?")

    # Optional: Chapter marker discovered by gap healing agents
    chapter_marker: Optional[Dict[str, Any]] = Field(
        None,
        description="Chapter metadata if this page is a chapter title page (discovered by gap healing)"
    )


__all__ = [
    "LabelStructurePageOutput",
]
