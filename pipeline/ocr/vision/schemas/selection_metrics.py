from pydantic import BaseModel, Field


class VisionSelectionMetrics(BaseModel):

    page_num: int
    processing_time_seconds: float
    cost_usd: float
    attempts: int
    tokens_total: int
    tokens_per_second: float
    model_used: str
    provider: str
    queue_time_seconds: float
    execution_time_seconds: float
    total_time_seconds: float
    ttft_seconds: float
    usage: dict

    selected_psm: int = Field(description="PSM mode selected by LLM (3, 4, or 6)")
    confidence: float = Field(description="LLM confidence in selection")
    reason: str = Field(description="LLM's explanation for selecting this PSM")
    alternatives_rejected: list[int] = Field(description="PSM modes not selected")
    agreement_similarity: float = Field(description="Similarity score from psm_agreement.json")
    agreement_category: str = Field(description="Agreement category (identical, minor_differences, etc.)")
