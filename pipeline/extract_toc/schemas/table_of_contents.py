from typing import List, Dict
from pydantic import BaseModel, Field

from .page_range import PageRange
from .toc_entry import ToCEntry


class TableOfContents(BaseModel):
    entries: List[ToCEntry] = Field(..., description="All ToC entries in order")
    toc_page_range: PageRange = Field(..., description="Pages where ToC appears")
    entries_by_level: Dict[int, int] = Field(..., description="Count of entries at each level (1, 2, 3)")
    parsing_confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in parsing accuracy")
    notes: List[str] = Field(default_factory=list, description="Parsing notes or warnings")
