"""
Batch LLM processing infrastructure.

Public API for batch processing with retries, rate limiting, and telemetry.

Usage:
    from infra.llm.batch import LLMBatchClient

    client = LLMBatchClient(max_workers=10, max_retries=5)
    results = client.process_batch(requests, on_event=handler, on_result=handler)
"""

from .client import LLMBatchClient
from .stats import BatchStats, BatchStatsTracker

__all__ = [
    'LLMBatchClient',
    'BatchStats',
    'BatchStatsTracker',
]
