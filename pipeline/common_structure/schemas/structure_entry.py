from typing import Optional, Literal, List
from pydantic import BaseModel, Field

from .text_content import SectionText, PageText, TextEdit


class StructureEntry(BaseModel):
    entry_id: str
    title: str
    level: int = Field(..., ge=1, le=3)
    entry_number: Optional[str] = None
    scan_page_start: int = Field(..., ge=1)
    scan_page_end: int = Field(..., ge=1)
    parent_id: Optional[str] = None
    confidence: float = Field(..., ge=0.0, le=1.0)
    source: Literal["toc", "heading", "reconciled"] = "toc"
    semantic_type: str = "chapter"

    # Matter classification (populated by LLM classification phase)
    matter_type: Literal["front_matter", "body", "back_matter"] = "body"

    # Text content (populated by text extraction phase)
    content: Optional[SectionText] = None
