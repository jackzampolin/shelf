"""Image region schema for detected images."""

from typing import Optional
from pydantic import BaseModel, Field, field_validator

from .bounding_box import BoundingBox


class ImageRegion(BaseModel):
    image_id: int = Field(..., ge=1, description="Unique image ID within page")
    bbox: BoundingBox = Field(..., description="Image bounding box")
    image_file: str = Field(..., description="Saved image filename")

    ocr_attempted: bool = Field(True, description="Whether OCR validation was attempted")
    ocr_text_recovered: Optional[str] = Field(None, description="If text found during validation, moved to blocks instead")

    @field_validator('bbox', mode='before')
    @classmethod
    def parse_bbox(cls, v):
        if isinstance(v, list):
            return BoundingBox.from_list(v)
        return v
