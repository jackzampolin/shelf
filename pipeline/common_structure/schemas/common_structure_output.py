from typing import List
from pydantic import BaseModel, Field

from .book_metadata import BookMetadata
from .page_reference import PageReference
from .structure_entry import StructureEntry


class CommonStructureOutput(BaseModel):
    metadata: BookMetadata
    page_references: List[PageReference]
    entries: List[StructureEntry]
    front_matter_pages: List[int] = Field(default_factory=list)
    back_matter_pages: List[int] = Field(default_factory=list)
    total_entries: int = Field(..., ge=0)
    total_chapters: int = Field(..., ge=0)
    total_parts: int = Field(default=0, ge=0)
    total_sections: int = Field(default=0, ge=0)
    extracted_at: str
    cost_usd: float = Field(..., ge=0.0)
    processing_time_seconds: float = Field(..., ge=0.0)
