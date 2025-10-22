"""
Base schemas for pipeline stage metrics and contracts.

Defines the metric contracts that stages must follow when tracking
checkpoint data. This enables type-safe metrics, automatic report
generation, and cross-stage analysis.
"""

from typing import Dict, Any, Optional, Type
from pydantic import BaseModel, Field


class BasePageMetrics(BaseModel):
    """
    Base metrics that ALL stages must track.

    These fields are the minimum required for any stage to provide
    useful checkpoint data and enable cross-stage cost/time analysis.
    """
    page_num: int = Field(..., ge=1, description="Page number processed")
    processing_time_seconds: float = Field(..., ge=0.0, description="Total time to process this page")
    cost_usd: float = Field(0.0, ge=0.0, description="Cost to process this page in USD")


class LLMPageMetrics(BasePageMetrics):
    """
    Metrics for stages that call LLM APIs.

    Extends base metrics with detailed LLM performance tracking:
    - Token usage and throughput
    - Time breakdown (queue, execution, TTFT)
    - Retry attempts
    - Model/provider information

    All vision-based stages (OCR metadata, Correction, Label) should
    use this or a subclass of it.
    """
    attempts: int = Field(..., ge=1, description="Number of attempts (including retries)")

    # Token metrics
    tokens_total: int = Field(..., ge=0, description="Total tokens in response")
    tokens_per_second: float = Field(..., ge=0.0, description="Token throughput")

    # Model information
    model_used: str = Field(..., description="Model that processed the request")
    provider: str = Field(..., description="Provider (e.g., 'openai', 'anthropic')")

    # Timing breakdown
    queue_time_seconds: float = Field(..., ge=0.0, description="Time waiting in queue")
    execution_time_seconds: float = Field(..., ge=0.0, description="Time executing request")
    total_time_seconds: float = Field(..., ge=0.0, description="Total time (queue + execution)")

    # Streaming metrics (optional)
    ttft_seconds: Optional[float] = Field(None, ge=0.0, description="Time to first token (streaming only)")

    # Raw usage data from provider (can have nested dicts like completion_tokens_details)
    usage: Dict[str, Any] = Field(default_factory=dict, description="Raw usage dict from API")


class StageContract(BaseModel):
    """
    Defines the full contract for a pipeline stage.

    This is a convenience class for documentation and validation.
    Stages define these as class attributes on BaseStage.
    """
    name: str = Field(..., description="Stage name (e.g., 'ocr', 'corrected')")
    dependencies: list[str] = Field(default_factory=list, description="Required upstream stages")

    input_schema: Optional[Type[BaseModel]] = Field(None, description="Schema of input data from dependencies")
    output_schema: Optional[Type[BaseModel]] = Field(None, description="Schema of output data written by stage")
    checkpoint_schema: Type[BaseModel] = Field(BasePageMetrics, description="Schema of metrics tracked in checkpoint")
