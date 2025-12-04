from typing import Optional, List, Literal
from pydantic import BaseModel, Field


class EnrichedToCEntry(BaseModel):
    entry_index: int = Field(..., ge=0)
    title: str
    scan_page: int = Field(..., ge=1)
    level: int = Field(..., ge=1)
    parent_index: Optional[int] = None
    source: Literal["toc", "discovered", "missing_found"]
    entry_number: Optional[str] = None
    printed_page_number: Optional[str] = None
    discovery_reasoning: Optional[str] = None
    label_structure_level: Optional[int] = None


class EnrichedTableOfContents(BaseModel):
    entries: List[EnrichedToCEntry]
    original_toc_count: int = Field(..., ge=0)
    discovered_count: int = Field(..., ge=0)
    total_entries: int = Field(..., ge=0)
