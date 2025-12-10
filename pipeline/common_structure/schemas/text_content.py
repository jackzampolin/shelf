from typing import List, Optional
from pydantic import BaseModel, Field


class PageText(BaseModel):
    """Text content from a single page within a section."""
    scan_page: int = Field(..., ge=1)
    printed_page: Optional[str] = None
    raw_text: str = Field(..., description="Original OCR markdown")
    cleaned_text: str = Field(..., description="After mechanical cleaning")


class TextEdit(BaseModel):
    """A single edit to apply to the text."""
    old_text: str = Field(..., min_length=1, description="Text to find")
    new_text: str = Field(..., description="Replacement text")
    reason: str = Field(..., description="Why this edit was made")


class SectionText(BaseModel):
    """Complete text content for a structure entry/section."""
    page_texts: List[PageText] = Field(default_factory=list)
    mechanical_text: str = Field("", description="After mechanical join")
    edits_applied: List[TextEdit] = Field(default_factory=list)
    final_text: str = Field("", description="After LLM polish")
    word_count: int = Field(0, ge=0)
    page_breaks: List[int] = Field(
        default_factory=list,
        description="Scan page numbers where breaks occur (for ePub markers)"
    )
