from typing import Optional
from pydantic import BaseModel, Field


class ToCEntry(BaseModel):
    entry_number: Optional[str] = Field(
        None,
        description="Entry numbering if present (e.g., '5', 'II', 'A', '1.1')"
    )
    title: str = Field(..., min_length=1, description="Entry title as shown in ToC")
    level: int = Field(1, ge=1, le=3, description="Visual hierarchy level (1=top-level, 2=nested, 3=deeply nested)")
    level_name: Optional[str] = Field(
        None,
        description="Semantic type of entry: 'volume', 'book', 'part', 'unit', 'chapter', 'section', 'subsection', 'act', 'scene', 'appendix'"
    )
    printed_page_number: Optional[str] = Field(
        None,
        description="PRINTED page number from ToC exactly as shown (may be roman 'ix' or arabic '15')"
    )
