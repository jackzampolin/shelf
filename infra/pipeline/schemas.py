from typing import Dict, Any, Optional, Type
from pydantic import BaseModel, Field


class BasePageMetrics(BaseModel):
    page_num: int = Field(..., ge=1, description="Page number processed")
    processing_time_seconds: float = Field(..., ge=0.0, description="Total time to process this page")
    cost_usd: float = Field(0.0, ge=0.0, description="Cost to process this page in USD")


class LLMPageMetrics(BasePageMetrics):
    attempts: int = Field(..., ge=1, description="Number of attempts (including retries)")

    tokens_total: int = Field(..., ge=0, description="Total tokens in response")
    tokens_per_second: float = Field(..., ge=0.0, description="Token throughput")

    model_used: str = Field(..., description="Model that processed the request")
    provider: str = Field(..., description="Provider (e.g., 'openai', 'anthropic')")

    queue_time_seconds: float = Field(..., ge=0.0, description="Time waiting in queue")
    execution_time_seconds: float = Field(..., ge=0.0, description="Time executing request")
    total_time_seconds: float = Field(..., ge=0.0, description="Total time (queue + execution)")

    ttft_seconds: Optional[float] = Field(None, ge=0.0, description="Time to first token (streaming only)")

    usage: Dict[str, Any] = Field(default_factory=dict, description="Raw usage dict from API")


class StageContract(BaseModel):
    name: str = Field(..., description="Stage name (e.g., 'ocr', 'corrected')")
    dependencies: list[str] = Field(default_factory=list, description="Required upstream stages")

    input_schema: Optional[Type[BaseModel]] = Field(None, description="Schema of input data from dependencies")
    output_schema: Optional[Type[BaseModel]] = Field(None, description="Schema of output data written by stage")
    checkpoint_schema: Type[BaseModel] = Field(BasePageMetrics, description="Schema of metrics tracked in checkpoint")
