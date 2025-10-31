from typing import List
from pydantic import BaseModel, Field

from .paragraph_correction import ParagraphCorrection


class BlockCorrection(BaseModel):
    block_num: int = Field(..., ge=1, description="Block number (matches OCR)")

    paragraphs: List[ParagraphCorrection] = Field(..., description="Paragraph-level corrections")
