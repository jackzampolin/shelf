from typing import Optional
from pydantic import BaseModel, Field


class ToCEntry(BaseModel):
    chapter_number: Optional[int] = Field(None, ge=1, description="Chapter number if present")
    title: str = Field(..., min_length=1, description="Chapter/section title as shown in ToC")
    printed_page_number: Optional[str] = Field(
        None,
        description="PRINTED page number from ToC exactly as shown (may be roman 'ix' or arabic '15')"
    )
    level: int = Field(1, ge=1, le=3, description="Hierarchy level (1=chapter, 2=section, 3=subsection)")
