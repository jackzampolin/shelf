from pydantic import BaseModel, Field
from typing import Optional, Literal, List


class LLMHeaderObservation(BaseModel):
    present: bool
    text: Optional[str]
    confidence: Literal["high", "medium", "low"]
    source_provider: Literal["mistral", "olm", "paddle"]


class LLMFooterObservation(BaseModel):
    present: bool
    text: Optional[str]
    confidence: Literal["high", "medium", "low"]
    source_provider: Literal["mistral", "olm", "paddle"]


class LLMPageNumberObservation(BaseModel):
    present: bool
    number: Optional[str]
    location: Optional[Literal["header", "footer", "margin"]]
    confidence: Literal["high", "medium", "low"]
    source_provider: Literal["mistral", "olm", "paddle"]


class LLMHeadingItem(BaseModel):
    level: int = Field(..., ge=1, le=6)
    text: str


class LLMHeadingObservation(BaseModel):
    present: bool
    headings: List[LLMHeadingItem] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"]
    source_provider: Literal["mistral", "olm", "paddle"]


class StructureExtractionResponse(BaseModel):
    header: LLMHeaderObservation
    footer: LLMFooterObservation
    page_number: LLMPageNumberObservation
    headings: LLMHeadingObservation
