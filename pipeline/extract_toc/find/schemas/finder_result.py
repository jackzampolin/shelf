from typing import Optional, Dict
from pydantic import BaseModel, Field

from .page_range import PageRange
from .structure_summary import StructureSummary


class FinderResult(BaseModel):
    toc_found: bool
    toc_page_range: Optional[PageRange] = None
    confidence: float = Field(ge=0.0, le=1.0)
    search_strategy_used: str
    pages_checked: int = 0
    reasoning: str
    structure_notes: Optional[Dict[int, str]] = None
    structure_summary: Optional[StructureSummary] = Field(
        None,
        description="Global structure analysis: hierarchy levels, visual patterns, numbering schemes"
    )
