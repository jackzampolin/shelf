"""
Report Schema

Quality-focused metrics for CSV report.
Filters checkpoint metrics to show only what matters for quality assessment.
"""

from pydantic import BaseModel, Field


class ParagraphCorrectPageReport(BaseModel):
    """
    Quality-focused report for Paragraph-Correct stage.

    Helps identify pages with correction issues:
    - Over-correction (low similarity, many changes)
    - Quality problems (low confidence after correction)
    - Pages needing review (high edit distance)
    """
    page_num: int = Field(..., ge=1, description="Page number")
    total_corrections: int = Field(..., ge=0, description="Paragraphs corrected")
    avg_confidence: float = Field(..., ge=0.0, le=1.0, description="Quality after correction (low = needs review)")
    text_similarity_ratio: float = Field(..., ge=0.0, le=1.0, description="Similarity to OCR (low = major changes)")
    characters_changed: int = Field(..., ge=0, description="Edit magnitude (high = significant rewrites)")
