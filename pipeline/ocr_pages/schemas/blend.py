from pydantic import BaseModel, Field


class BlendedOcrPageOutput(BaseModel):
    page_num: int = Field(..., ge=1)
    markdown: str = Field(...)
    char_count: int = Field(..., ge=0)
    model_used: str = Field(...)


class BlendedOcrPageMetrics(BaseModel):
    page_num: int = Field(..., ge=1)
    cost_usd: float = Field(..., ge=0.0)
    time_seconds: float = Field(..., ge=0.0)
    char_count: int = Field(..., ge=0)
    prompt_tokens: int = Field(..., ge=0)
    completion_tokens: int = Field(..., ge=0)
