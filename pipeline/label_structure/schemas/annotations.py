from pydantic import BaseModel, Field
from typing import List, Optional, Literal


class ReferenceMarker(BaseModel):
    """A reference marker found in body text (could be footnote, endnote, or citation)."""
    marker_text: str = Field(..., description="Marker symbol/number (e.g., '1', '*', '†')")
    marker_type: Literal["numeric", "symbol", "letter", "bracketed"] = Field(
        ..., description="Type: numeric (1,2,3), symbol (*,†,‡), letter (a,b,c), bracketed ([1],(1))"
    )
    is_superscript: bool = Field(..., description="Appears as superscript in text?")
    context: str = Field(..., description="Surrounding text context (20 chars before/after)")
    confidence: Literal["high", "medium", "low"]


class FootnoteContent(BaseModel):
    """Footnote content found at bottom of the SAME PAGE as marker."""
    marker: str = Field(..., description="Matching marker (e.g., '1', '*')")
    content: str = Field(..., description="Full footnote text content")
    confidence: Literal["high", "medium", "low"]
    source_provider: Literal["blend"]


class CrossReference(BaseModel):
    """Internal cross-reference link (e.g., 'see Chapter 3', 'cf. page 42')."""
    link_text: str = Field(..., description="Display text of the link")
    target_description: str = Field(..., description="Description of target (e.g., 'Chapter 3', 'page 42')")
    target_type: Literal["chapter", "section", "page", "figure", "table", "other"] = Field(
        ..., description="Type of reference target"
    )
    confidence: Literal["high", "medium", "low"]


class AnnotationsOutput(BaseModel):
    """Output from Pass 3: LLM content annotations extraction."""

    # Reference markers in body text (footnotes/endnotes/citations)
    markers_present: bool = Field(..., description="Any reference markers found in body text?")
    markers: List[ReferenceMarker] = Field(
        default_factory=list,
        description="All reference markers found (footnote/endnote/citation markers)"
    )

    # Footnote content (at bottom of THIS PAGE)
    footnotes_present: bool = Field(..., description="Footnote content at bottom of page?")
    footnotes: List[FootnoteContent] = Field(
        default_factory=list,
        description="Footnote content found at bottom of this specific page"
    )

    # Cross-references and internal links
    cross_references_present: bool = Field(..., description="Internal links/cross-refs found?")
    cross_references: List[CrossReference] = Field(
        default_factory=list,
        description="Internal document links (e.g., 'see Chapter 3')"
    )

    # Visual layout indicators (help distinguish footnotes from endnotes)
    has_horizontal_rule: bool = Field(
        False,
        description="Horizontal line separating body text from footnotes?"
    )
    has_small_text_at_bottom: bool = Field(
        False,
        description="Visually smaller text at bottom (footnote indicator)?"
    )

    # Overall confidence
    confidence: Literal["high", "medium", "low"]


__all__ = [
    "ReferenceMarker",
    "FootnoteContent",
    "CrossReference",
    "AnnotationsOutput",
]
