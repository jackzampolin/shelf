"""
Checkpoint Metrics Schema

What we track in checkpoint for each page.
Extends LLMPageMetrics with correction-specific quality metrics.
"""

from pydantic import Field
from infra.pipeline.schemas import LLMPageMetrics


class ParagraphCorrectPageMetrics(LLMPageMetrics):
    """
    Checkpoint metrics for Paragraph-Correct stage.

    Extends LLMPageMetrics with correction-specific quality metrics.
    Tracks both LLM performance (tokens, timing, cost) and correction
    quality (how many corrections made, confidence).
    """
    # Correction-specific metrics
    total_corrections: int = Field(..., ge=0, description="Number of paragraphs with corrections")
    avg_confidence: float = Field(..., ge=0.0, le=1.0, description="Average text confidence after correction")

    # Similarity metrics (OCR vs corrected text)
    text_similarity_ratio: float = Field(..., ge=0.0, le=1.0, description="Text similarity between OCR and corrected (1.0 = identical)")
    characters_changed: int = Field(..., ge=0, description="Number of characters modified from OCR")
