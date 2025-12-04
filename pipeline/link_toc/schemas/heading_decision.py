from typing import Optional
from pydantic import BaseModel, Field


class HeadingDecision(BaseModel):
    scan_page: Optional[int] = Field(None, ge=1)
    heading_text: str
    include: bool
    title: Optional[str] = None
    level: Optional[int] = Field(None, ge=1)
    entry_number: Optional[str] = None
    reasoning: str
