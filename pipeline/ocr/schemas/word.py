from pydantic import BaseModel, Field, field_validator

from .bounding_box import BoundingBox

class Word(BaseModel):
    text: str = Field(..., min_length=1, description="Word text")
    bbox: BoundingBox = Field(..., description="Word bounding box")
    confidence: float = Field(..., ge=0.0, le=1.0, description="OCR confidence for this word (0.0-1.0)")

    @field_validator('bbox', mode='before')
    @classmethod
    def parse_bbox(cls, v):
        if isinstance(v, list):
            return BoundingBox.from_list(v)
        return v
