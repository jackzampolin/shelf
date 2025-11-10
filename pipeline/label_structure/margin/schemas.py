from typing import Literal, Optional
from pydantic import BaseModel, Field


class HeaderObservation(BaseModel):
    exists: bool = Field(
        ...,
        description="Is there a header in the top margin area?"
    )

    text: Optional[str] = Field(
        None,
        max_length=200,
        description="Header text if visible (null if no header)"
    )

    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence in header observation (0.0-1.0)"
    )


class FooterObservation(BaseModel):
    exists: bool = Field(
        ...,
        description="Is there a footer visible in bottom margin?"
    )

    text: Optional[str] = Field(
        None,
        max_length=200,
        description="Footer text if visible (null if no footer)"
    )

    position: Optional[Literal["left", "center", "right"]] = Field(
        None,
        description="Footer alignment (null if no footer)"
    )

    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence in footer observation (0.0-1.0)"
    )


class PageNumberObservation(BaseModel):
    exists: bool = Field(
        ...,
        description="Is there a page number visible?"
    )

    number: Optional[str] = Field(
        None,
        max_length=20,
        description="Page number as shown (e.g., '15', 'xiv', '3-12') (null if none)"
    )

    position: Optional[Literal["top_center", "top_outer", "top_inner", "bottom_center", "bottom_outer", "bottom_inner"]] = Field(
        None,
        description="Page number location (null if none)"
    )

    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence in page number observation (0.0-1.0)"
    )


class MarginObservation(BaseModel):
    header: HeaderObservation
    footer: FooterObservation
    page_number: PageNumberObservation
    reasoning: str = Field(
        ...,
        max_length=500,
        description="Brief explanation of observations and confidence levels"
    )
