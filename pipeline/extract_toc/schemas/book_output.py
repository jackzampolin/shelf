from typing import Optional
from pydantic import BaseModel, Field

from .table_of_contents import TableOfContents


class ExtractTocBookOutput(BaseModel):
    toc: Optional[TableOfContents] = Field(None)
    search_strategy: str
    phase_costs: dict = Field(default_factory=dict)
