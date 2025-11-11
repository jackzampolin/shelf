from typing import List, Optional
from pydantic import BaseModel, Field


class ImageBBox(BaseModel):
    """Bounding box for detected image in page."""
    top_left_x: int = Field(..., description="Top-left X coordinate")
    top_left_y: int = Field(..., description="Top-left Y coordinate")
    bottom_right_x: int = Field(..., description="Bottom-right X coordinate")
    bottom_right_y: int = Field(..., description="Bottom-right Y coordinate")
    image_base64: Optional[str] = Field(None, description="Base64-encoded image data if requested")


class PageDimensions(BaseModel):
    """Page dimensions and DPI info."""
    width: int = Field(..., description="Page width in pixels")
    height: int = Field(..., description="Page height in pixels")
    dpi: Optional[int] = Field(None, description="Page DPI if available")


class MistralOcrPageOutput(BaseModel):
    """Schema for mistral-ocr stage output (per page)."""

    page_num: int = Field(..., ge=1, description="Page number in book")

    # Text content
    markdown: str = Field(..., description="Markdown-formatted text with preserved structure")
    char_count: int = Field(..., ge=0, description="Character count of extracted text")

    # Page metadata
    dimensions: PageDimensions = Field(..., description="Page dimensions and DPI")

    # Detected images with bounding boxes
    images: List[ImageBBox] = Field(default_factory=list, description="Detected images with bounding boxes")

    # Processing metadata
    model_used: str = Field(..., description="Mistral model used (e.g., mistral-ocr-latest)")
    processing_cost: float = Field(..., ge=0.0, description="Cost in USD for this page")
