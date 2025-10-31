"""
LLM Response Schemas

What the LLM returns during correction (before we add metadata).
These schemas are used to generate the structured response format.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class ParagraphCorrection(BaseModel):
    """Correction information for a single paragraph."""

    par_num: int = Field(..., ge=1, description="Paragraph number within block (matches OCR)")

    # Only present if corrections were made - outputs FULL corrected paragraph text
    text: Optional[str] = Field(None, description="Full corrected paragraph text (omit if no errors found)")
    notes: Optional[str] = Field(None, description="Brief explanation of changes made (e.g., 'Fixed hyphenation, 2 OCR errors')")

    # Confidence in the text quality (1.0 if no changes needed)
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in text quality")


class BlockCorrection(BaseModel):
    """Corrections for a single block (no classification)."""

    block_num: int = Field(..., ge=1, description="Block number (matches OCR)")

    paragraphs: List[ParagraphCorrection] = Field(..., description="Paragraph-level corrections")


class CorrectionLLMResponse(BaseModel):
    """
    LLM response structure for correction stage.

    This is what the LLM returns. The stage adds metadata to create ParagraphCorrectPageOutput.
    Use this model to generate the JSON schema for response_format.
    """
    blocks: List[BlockCorrection] = Field(..., description="Block corrections")
