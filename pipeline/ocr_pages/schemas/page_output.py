from pydantic import BaseModel, Field


class OcrPagesPageOutput(BaseModel):
    page_num: int = Field(..., ge=1, description="Page number in book")
    text: str = Field(..., description="Markdown-formatted OCR text from OlmOCR")
    char_count: int = Field(..., ge=0, description="Character count of extracted text")
