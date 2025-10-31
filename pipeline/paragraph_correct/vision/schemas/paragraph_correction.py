from typing import Optional
from pydantic import BaseModel, Field


class ParagraphCorrection(BaseModel):
    par_num: int = Field(..., ge=1, description="Paragraph number within block (matches OCR)")

    text: Optional[str] = Field(None, description="Full corrected paragraph text (omit if no errors found)")
    notes: Optional[str] = Field(None, description="Brief explanation of changes made (e.g., 'Fixed hyphenation, 2 OCR errors')")

    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in text quality")
