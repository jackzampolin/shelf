from typing import Optional, Literal
from pydantic import BaseModel, Field


class PageReference(BaseModel):
    scan_page: int = Field(..., ge=1)
    printed_page: Optional[str] = None
    numbering_style: Literal["roman", "arabic", "letter", "none"] = "none"
