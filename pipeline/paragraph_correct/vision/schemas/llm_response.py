from typing import List, Optional
from pydantic import BaseModel, Field


class ParagraphCorrection(BaseModel):
    par_num: int = Field(..., ge=1, description="Paragraph number within block (matches OCR)")

    text: Optional[str] = Field(None, description="Full corrected paragraph text (omit if no errors found)")
    notes: Optional[str] = Field(None, description="Brief explanation of changes made (e.g., 'Fixed hyphenation, 2 OCR errors')")

    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in text quality")


class BlockCorrection(BaseModel):
    block_num: int = Field(..., ge=1, description="Block number (matches OCR)")

    paragraphs: List[ParagraphCorrection] = Field(..., description="Paragraph-level corrections")


class CorrectionLLMResponse(BaseModel):
    blocks: List[BlockCorrection] = Field(..., description="Block corrections")
