"""
Batch LLM processing infrastructure.

Public API for batch processing with retries, rate limiting, and telemetry.

Usage:
    # High-level stage API (most common):
    from infra.llm.batch import LLMBatchProcessor, LLMBatchConfig

    processor = LLMBatchProcessor(
        storage=storage,
        stage_name="label-pages",
        logger=logger,
        config=LLMBatchConfig(model="grok-4-fast")
    )
    stats = processor.process(
        items=pages,
        request_builder=build_request,
        result_handler=handle_result
    )

    # Low-level client API (advanced):
    from infra.llm.batch import LLMBatchClient

    client = LLMBatchClient(max_workers=10, max_retries=5)
    results = client.process_batch(requests, on_event=handler, on_result=handler)
"""

from .client import LLMBatchClient
from .stats import BatchStats, BatchStatsTracker
from .processor import LLMBatchProcessor, LLMBatchConfig

__all__ = [
    # High-level stage API
    'LLMBatchProcessor',
    'LLMBatchConfig',
    # Low-level client API
    'LLMBatchClient',
    'BatchStats',
    'BatchStatsTracker',
]
