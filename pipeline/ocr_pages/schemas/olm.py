from pydantic import BaseModel, Field
from typing import Optional, Literal


class OlmOcrPageOutput(BaseModel):
    page_num: int = Field(..., ge=1, description="Page number in book")
    text: str = Field(..., description="Markdown-formatted OCR text from OlmOCR (without front matter)")
    char_count: int = Field(..., ge=0, description="Character count of extracted text")

    # OlmOCR front matter metadata
    primary_language: Optional[str] = Field(None, description="Primary language detected (e.g., 'en', 'es')")
    is_rotation_valid: bool = Field(True, description="Whether page rotation is correct")
    rotation_correction: Literal[0, 90, 180, 270] = Field(0, description="Rotation degrees needed to correct page")
    is_table: bool = Field(False, description="Whether page contains primarily tabular data")
    is_diagram: bool = Field(False, description="Whether page contains primarily diagrams/figures")


class OlmOcrPageMetrics(BaseModel):
    page_num: int = Field(..., ge=1, description="Page number processed")
    cost_usd: float = Field(..., ge=0.0, description="API cost for this page")
    time_seconds: float = Field(..., ge=0.0, description="Processing time for this page")
    char_count: int = Field(..., ge=0, description="Characters extracted")
    prompt_tokens: int = Field(..., ge=0, description="Prompt tokens used")
    completion_tokens: int = Field(..., ge=0, description="Completion tokens used")
