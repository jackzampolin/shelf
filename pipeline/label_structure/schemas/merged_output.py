from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from .mechanical import HeadingItem, PatternHints


class PageNumberObservation(BaseModel):
    present: bool
    number: Optional[str] = ""
    location: Optional[Literal["header", "footer", "margin", ""]] = None
    reasoning: str = ""
    source_provider: Literal["blend", "gap_healing_simple", "agent_healed"] = "blend"


class RunningHeaderObservation(BaseModel):
    present: bool
    text: Optional[str] = ""
    reasoning: str = ""


class LabelStructurePageOutput(BaseModel):
    # From mechanical phase
    headings_present: bool
    headings: List[HeadingItem] = Field(default_factory=list)
    pattern_hints: PatternHints = Field(default_factory=PatternHints)

    # From unified phase (+ gap healing patches)
    page_number: PageNumberObservation
    running_header: RunningHeaderObservation


__all__ = ["LabelStructurePageOutput", "PageNumberObservation", "RunningHeaderObservation"]
