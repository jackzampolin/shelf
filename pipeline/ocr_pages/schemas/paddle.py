from pydantic import BaseModel, Field


class PaddleOcrPageOutput(BaseModel):
    page_num: int = Field(..., ge=1, description="Page number in book")
    text: str = Field(..., description="Markdown-formatted OCR text from PaddleOCR-VL")
    char_count: int = Field(..., ge=0, description="Character count of extracted text")
    has_table: bool = Field(False, description="Whether page contains table(s)")
    has_formula: bool = Field(False, description="Whether page contains mathematical formulas/equations")
    has_chart: bool = Field(False, description="Whether page contains charts/diagrams/figures")


class PaddleOcrPageMetrics(BaseModel):
    page_num: int = Field(..., ge=1, description="Page number processed")
    cost_usd: float = Field(..., ge=0.0, description="API cost for this page")
    time_seconds: float = Field(..., ge=0.0, description="Processing time for this page")
    char_count: int = Field(..., ge=0, description="Characters extracted")
    prompt_tokens: int = Field(..., ge=0, description="Prompt tokens used")
    completion_tokens: int = Field(..., ge=0, description="Completion tokens used")
