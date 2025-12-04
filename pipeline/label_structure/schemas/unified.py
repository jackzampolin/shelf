from pydantic import BaseModel
from typing import Literal, Optional


class PageNumberExtraction(BaseModel):
    present: bool
    number: Optional[str] = ""
    location: Optional[Literal["header", "footer", "margin", ""]] = None
    reasoning: str = ""


class RunningHeaderExtraction(BaseModel):
    present: bool
    text: Optional[str] = ""
    reasoning: str = ""


class UnifiedExtractionOutput(BaseModel):
    page_number: PageNumberExtraction
    running_header: RunningHeaderExtraction


__all__ = ["UnifiedExtractionOutput", "PageNumberExtraction", "RunningHeaderExtraction"]
