"""
LLM subsystem for OpenRouter API integration.

Provides:
- LLMClient: Single LLM calls with retry logic and vision support
- LLMBatchClient: Batch processing with queue-based retries
- Data models: Request/result structures for batch processing
- Metrics: Helper utilities for converting results to checkpoint metrics
- Pricing: Dynamic cost calculation from OpenRouter API
- RateLimiter: Token bucket rate limiting
"""

from infra.llm.client import LLMClient
from infra.llm.batch import (
    LLMBatchClient,
    RequestPhase,
    RequestStatus,
    BatchStats,
)
from infra.llm.models import (
    LLMRequest,
    LLMResult,
    LLMEvent,
    EventData,
)
from infra.llm.metrics import llm_result_to_metrics
from infra.llm.pricing import PricingCache, CostCalculator, calculate_cost
from infra.llm.rate_limiter import RateLimiter

__all__ = [
    "LLMClient",
    "LLMBatchClient",
    "LLMRequest",
    "LLMResult",
    "LLMEvent",
    "EventData",
    "RequestPhase",
    "RequestStatus",
    "BatchStats",
    "llm_result_to_metrics",
    "PricingCache",
    "CostCalculator",
    "calculate_cost",
    "RateLimiter",
]
