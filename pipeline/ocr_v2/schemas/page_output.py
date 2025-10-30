"""OCR page output schema."""

from typing import List
from pydantic import BaseModel, Field, field_validator

from .page_dimensions import PageDimensions
from .block import Block
from .image_region import ImageRegion


class OCRPageOutput(BaseModel):
    """
    Complete OCR output for a single page.

    This is the schema we save to page_XXXX.json files.
    Designed to be input to correction stage (multimodal LLM).
    """
    page_number: int = Field(..., ge=1, description="Page number in book")
    page_dimensions: PageDimensions = Field(..., description="Page dimensions")
    ocr_timestamp: str = Field(..., description="ISO format timestamp")

    blocks: List[Block] = Field(default_factory=list, description="Text blocks detected by Tesseract")
    images: List[ImageRegion] = Field(default_factory=list, description="Images detected via OpenCV")

    @field_validator('blocks')
    @classmethod
    def validate_blocks(cls, blocks):
        """Ensure block numbers are unique."""
        block_nums = [b.block_num for b in blocks]
        if len(block_nums) != len(set(block_nums)):
            raise ValueError("Block numbers must be unique within page")
        return blocks

    @field_validator('images')
    @classmethod
    def validate_images(cls, images):
        """Ensure image IDs are unique."""
        image_ids = [img.image_id for img in images]
        if len(image_ids) != len(set(image_ids)):
            raise ValueError("Image IDs must be unique within page")
        return images

    def get_isolated_blocks(self) -> List[Block]:
        """Get likely headers/footers/captions (single-paragraph blocks)."""
        return [b for b in self.blocks if b.is_isolated]

    def get_continuous_blocks(self) -> List[Block]:
        """Get likely body text (multi-paragraph blocks)."""
        return [b for b in self.blocks if not b.is_isolated]

    def get_all_text(self) -> str:
        """Get all text from all blocks concatenated."""
        return "\n\n".join(b.text for b in self.blocks)

    def find_nearby_blocks(self, image: ImageRegion, proximity: int = 100) -> List[Block]:
        """
        Find blocks near an image (for caption detection).

        Args:
            image: Image region to check
            proximity: Maximum distance in pixels

        Returns:
            List of blocks within proximity distance
        """
        nearby = []
        img_y = image.bbox.y_center

        for block in self.blocks:
            block_y = block.bbox.y_center
            distance = abs(img_y - block_y)

            if distance <= proximity:
                nearby.append(block)

        return nearby
