from pydantic import Field
from infra.pipeline.schemas import LLMPageMetrics


class ParagraphCorrectPageMetrics(LLMPageMetrics):
    total_corrections: int = Field(..., ge=0, description="Number of paragraphs with corrections")
    avg_confidence: float = Field(..., ge=0.0, le=1.0, description="Average text confidence after correction")
    text_similarity_ratio: float = Field(..., ge=0.0, le=1.0, description="Text similarity between OCR and corrected (1.0 = identical)")
    characters_changed: int = Field(..., ge=0, description="Number of characters modified from OCR")
