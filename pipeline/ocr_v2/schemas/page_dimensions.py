"""Page dimensions schema."""

from pydantic import BaseModel, Field


class PageDimensions(BaseModel):
    """Page dimensions in pixels."""
    width: int = Field(..., ge=1, description="Page width in pixels")
    height: int = Field(..., ge=1, description="Page height in pixels")
