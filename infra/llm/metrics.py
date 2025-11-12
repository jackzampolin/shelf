"""
LLM Metrics Utilities

Helper functions for converting LLM results to metrics.
Provides clean abstraction for recording LLM metrics to MetricsManager.
"""

from typing import Dict, Any, Optional

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
        # Base fields (match MetricsManager standard names)
        "page_num": page_num,
        "cost_usd": result.cost_usd,
        "time_seconds": result.total_time_seconds,
        "tokens": result.tokens_received,

        # LLM-specific fields
        "attempts": result.attempts,
        "model_used": result.model_used,
        "provider": result.provider,

        # Timing breakdown
        "queue_time_seconds": result.queue_time_seconds,
        "execution_time_seconds": result.execution_time_seconds,

        # Token breakdown (extracted from usage dict for easy access)
        "prompt_tokens": result.usage.get("prompt_tokens", 0),
        "completion_tokens": result.usage.get("completion_tokens", 0),
        "reasoning_tokens": result.usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0),

        # Raw usage data (kept for compatibility)
        "usage": result.usage,
    }

    # Merge stage-specific fields
    if extra_fields:
        metrics.update(extra_fields)

    return metrics


def record_llm_result(
    metrics_manager,
    key: str,
    result: LLMResult,
    page_num: int,
    extra_fields: Optional[Dict[str, Any]] = None,
    accumulate: bool = False
):
    """
    Record LLMResult directly to MetricsManager with proper field mapping.

    Encapsulates the entire conversion from LLMResult → metrics dict → MetricsManager.
    Stages don't need to know about field name mapping or what goes into custom_metrics.

    Args:
        metrics_manager: MetricsManager instance to record to
        key: Metric key (e.g., "page_0042")
        result: LLMResult from batch processor
        page_num: Page number being processed
        extra_fields: Optional stage-specific fields to include in custom_metrics
        accumulate: Whether to accumulate costs/times (default: False)

    Example:
        >>> from infra.llm.metrics import record_llm_result
        >>>
        >>> # In stage result handler:
        >>> record_llm_result(
        ...     metrics_manager=stage_storage.metrics_manager,
        ...     key=f"page_{page_num:04d}",
        ...     result=result,
        ...     page_num=page_num,
        ...     extra_fields={'stage': 'stage1', 'corrections': 5}
        ... )
    """
    # Convert LLMResult to metrics dict (includes all LLM fields)
    metrics = llm_result_to_metrics(result, page_num, extra_fields)

    # Extract top-level fields for MetricsManager
    cost_usd = metrics.pop('cost_usd', 0.0)
    time_seconds = metrics.pop('time_seconds', 0.0)
    tokens = metrics.pop('tokens', 0)

    # Remove page_num from custom_metrics (it's not custom, it's standard)
    metrics.pop('page_num', None)

    # Everything else goes to custom_metrics:
    # - prompt_tokens, completion_tokens, reasoning_tokens
    # - execution_time_seconds, queue_time_seconds
    # - model_used, provider, attempts
    # - usage dict (raw API response)
    # - Any extra_fields provided by stage
    metrics_manager.record(
        key=key,
        cost_usd=cost_usd,
        time_seconds=time_seconds,
        tokens=tokens,
        custom_metrics=metrics,
        accumulate=accumulate
    )
