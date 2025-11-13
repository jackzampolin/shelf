from typing import Optional, Literal
from pydantic import BaseModel, Field


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
