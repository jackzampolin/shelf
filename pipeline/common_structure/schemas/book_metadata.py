from typing import Optional
from pydantic import BaseModel, Field


class BookMetadata(BaseModel):
    scan_id: str
    title: Optional[str] = None
    author: Optional[str] = None
    publisher: Optional[str] = None
    publication_year: Optional[int] = None
    language: str = "en"
    total_scan_pages: int = Field(..., ge=1)
