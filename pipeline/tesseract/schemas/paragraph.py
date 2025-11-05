from pydantic import BaseModel, Field


class TesseractParagraph(BaseModel):
    """Single paragraph from Tesseract OCR output."""
    par_num: int = Field(..., ge=0, description="Paragraph number within page")
    text: str = Field(..., description="Paragraph text content")
    confidence: float = Field(..., ge=0.0, le=1.0, description="OCR confidence (0.0-1.0)")
