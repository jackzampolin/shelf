"""
LLM Metrics Utilities

Helper functions for converting LLM results to checkpoint metrics.
Eliminates duplicate metrics mapping code across stages.
"""

from typing import Dict, Any

from .models import LLMResult


def llm_result_to_metrics(
    result: LLMResult,
    page_num: int,
    extra_fields: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Convert LLMResult to LLMPageMetrics dictionary.

    Extracts all standard LLM metrics from the result and optionally
    merges stage-specific fields. This eliminates duplicate mapping
    code across vision-based stages (correction, label, etc.).

    Args:
        result: LLM result from batch_client
        page_num: Page number being processed
        extra_fields: Optional stage-specific metrics to merge

    Returns:
        Dict with all LLMPageMetrics fields ready for Pydantic validation

    Example:
        >>> metrics = llm_result_to_metrics(
        ...     result=result,
        ...     page_num=42,
        ...     extra_fields={
        ...         "total_corrections": 5,
        ...         "avg_confidence": 0.95,
        ...     }
        ... )
        >>> validated = ParagraphCorrectPageMetrics(**metrics)
    """
    metrics = {
        # Base fields
        "page_num": page_num,
        "processing_time_seconds": result.total_time_seconds,
        "cost_usd": result.cost_usd,

        # LLM-specific fields
        "attempts": result.attempts,
        "tokens_total": result.tokens_received,
        "tokens_per_second": result.tokens_per_second,
        "model_used": result.model_used,
        "provider": result.provider,

        # Timing breakdown
        "queue_time_seconds": result.queue_time_seconds,
        "execution_time_seconds": result.execution_time_seconds,
        "total_time_seconds": result.total_time_seconds,
        "ttft_seconds": result.ttft_seconds,

        # Raw usage data
        "usage": result.usage,
    }

    # Merge stage-specific fields
    if extra_fields:
        metrics.update(extra_fields)

    return metrics
