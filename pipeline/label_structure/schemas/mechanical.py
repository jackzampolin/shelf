from pydantic import BaseModel, Field
from typing import List, Literal


class HeadingItem(BaseModel):
    """A heading extracted from Mistral markdown."""
    level: int = Field(..., ge=1, le=6, description="Heading level (1-6)")
    text: str = Field(..., description="Heading text content")
    line_number: int = Field(..., description="Line number in Mistral markdown")


class PatternHints(BaseModel):
    """Mechanical pattern detection hints for downstream passes."""

    # Footnote indicators
    has_mistral_footnote_refs: bool = Field(
        False,
        description="Mistral markdown contains [^N] footnote references"
    )
    mistral_footnote_count: int = Field(0, description="Count of [^N] patterns")

    has_repeated_symbols: bool = Field(
        False,
        description="Multiple instances of same symbol (e.g., *, †) suggesting footnotes"
    )
    repeated_symbol: str = Field("", description="The repeated symbol if detected")
    repeated_symbol_count: int = Field(0, description="How many times symbol appears")

    # Endnote indicators
    has_mistral_endnote_refs: bool = Field(
        False,
        description="Mistral contains ${ }^{N}$ endnote marker patterns"
    )
    mistral_endnote_markers: List[str] = Field(
        default_factory=list,
        description="Extracted endnote numbers (e.g., ['26', '27'])"
    )

    # Chart/table indicators
    has_olm_chart_tags: bool = Field(
        False,
        description="OLM contains <></> chart indicator tags"
    )
    olm_chart_count: int = Field(0, description="Count of <></> patterns in OLM")

    # Image indicators
    has_mistral_images: bool = Field(
        False,
        description="Mistral markdown contains ![alt](img.jpeg) image references"
    )
    mistral_image_refs: List[str] = Field(
        default_factory=list,
        description="Extracted image filenames (e.g., ['img-0.jpeg', 'img-1.jpeg'])"
    )


class MechanicalExtractionOutput(BaseModel):
    """Output from Pass 1: Mechanical extraction of headings and patterns."""

    # Headings
    headings_present: bool = Field(..., description="Any headings found?")
    headings: List[HeadingItem] = Field(default_factory=list, description="Extracted headings")

    # Pattern hints for downstream passes
    pattern_hints: PatternHints = Field(default_factory=PatternHints)

    # Metadata
    source: Literal["mistral-markdown"] = "mistral-markdown"
    extraction_method: Literal["regex"] = "regex"


__all__ = [
    "HeadingItem",
    "PatternHints",
    "MechanicalExtractionOutput",
]
