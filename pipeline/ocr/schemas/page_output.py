from typing import List
from pydantic import BaseModel, Field, field_validator

from .page_dimensions import PageDimensions
from .block import Block
from .image_region import ImageRegion


class OCRPageOutput(BaseModel):
    page_number: int = Field(..., ge=1, description="Page number in book")
    page_dimensions: PageDimensions = Field(..., description="Page dimensions")
    ocr_timestamp: str = Field(..., description="ISO format timestamp")

    blocks: List[Block] = Field(default_factory=list, description="Text blocks detected by Tesseract")
    images: List[ImageRegion] = Field(default_factory=list, description="Images detected via OpenCV")

    @field_validator('blocks')
    @classmethod
    def validate_blocks(cls, blocks):
        block_nums = [b.block_num for b in blocks]
        if len(block_nums) != len(set(block_nums)):
            raise ValueError("Block numbers must be unique within page")
        return blocks

    @field_validator('images')
    @classmethod
    def validate_images(cls, images):
        image_ids = [img.image_id for img in images]
        if len(image_ids) != len(set(image_ids)):
            raise ValueError("Image IDs must be unique within page")
        return images

    def get_isolated_blocks(self) -> List[Block]:
        return [b for b in self.blocks if b.is_isolated]

    def get_continuous_blocks(self) -> List[Block]:
        return [b for b in self.blocks if not b.is_isolated]

    def get_all_text(self) -> str:
        return "\n\n".join(b.text for b in self.blocks)

    def find_nearby_blocks(self, image: ImageRegion, proximity: int = 100) -> List[Block]:
        nearby = []
        img_y = image.bbox.y_center

        for block in self.blocks:
            block_y = block.bbox.y_center
            distance = abs(img_y - block_y)

            if distance <= proximity:
                nearby.append(block)

        return nearby
