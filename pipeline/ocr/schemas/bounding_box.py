from typing import List
from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    x: int = Field(..., ge=0, description="X coordinate of top-left corner")
    y: int = Field(..., ge=0, description="Y coordinate of top-left corner")
    width: int = Field(..., ge=0, description="Width of region")
    height: int = Field(..., ge=0, description="Height of region")

    @classmethod
    def from_list(cls, bbox: List[int]) -> "BoundingBox":
        if len(bbox) != 4:
            raise ValueError(f"BoundingBox requires 4 values, got {len(bbox)}")
        return cls(x=bbox[0], y=bbox[1], width=bbox[2], height=bbox[3])

    def to_list(self) -> List[int]:
        return [self.x, self.y, self.width, self.height]

    @property
    def y_center(self) -> float:
        return self.y + (self.height / 2)
