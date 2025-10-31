from pydantic import BaseModel, Field

from .block_type import BlockType


class BlockClassification(BaseModel):
    block_num: int = Field(..., ge=1, description="Block number (matches OCR)")
    classification: BlockType = Field(..., description="Classified content type")
    classification_confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in classification")
