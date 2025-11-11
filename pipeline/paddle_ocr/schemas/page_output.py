from pydantic import BaseModel, Field

class PaddleOcrPageOutput(BaseModel):
    page_num: int = Field(..., ge=1, description="Page number in book")
    text: str = Field(..., description="Markdown-formatted OCR text from PaddleOCR-VL")
    char_count: int = Field(..., ge=0, description="Character count of extracted text")
    has_table: bool = Field(False, description="Whether page contains table(s)")
    has_formula: bool = Field(False, description="Whether page contains mathematical formulas/equations")
    has_chart: bool = Field(False, description="Whether page contains charts/diagrams/figures")
