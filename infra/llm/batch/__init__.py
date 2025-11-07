"""LLM Batch Processing Infrastructure

This package provides parallel execution of LLM API requests with rate limiting,
retries, and comprehensive progress tracking.

## Architecture

**For pipeline stages (most common):**
Use `LLMBatchProcessor` from processor.py:

    from infra.llm.batch import LLMBatchProcessor, LLMBatchConfig

    config = LLMBatchConfig(
        model="anthropic/claude-sonnet-4",
        max_workers=10,
        max_retries=3,
        batch_name="My Stage"
    )
    processor = LLMBatchProcessor(storage, stage_name, logger, config)
    processor.process(items, request_builder, result_handler)

This handles request preparation, progress display, and metrics aggregation.

**For custom batch operations:**
Use `LLMBatchClient` from client.py:

    from infra.llm.batch import LLMBatchClient

    client = LLMBatchClient(max_workers=10, logger=logger)
    results = client.process_batch(requests, on_event=..., on_result=...)

This gives you direct control over batching without stage-specific wrappers.

## Internal Components (rarely imported directly)

- **executor.py**: Executes individual LLM requests with timeout/retry
- **worker/**: Worker pool that manages parallel execution
  - pool.py: Main orchestration
  - handlers.py: Result handling (success/retry/failure/crash)
  - queue.py: Request queue management
  - rate_limit.py: Rate limit checking
  - tracking.py: Request phase tracking
- **callbacks.py**: Wraps callbacks to track stats
- **stats.py**: Aggregates batch execution statistics
- **schemas/**: Data models (BatchConfig, BatchStats, RequestPhase, RequestStatus)
- **progress/**: Progress display helpers (rollups, recent completions)

## Request Flow

Stage → LLMBatchProcessor → LLMBatchClient → WorkerPool → RequestExecutor → LLMClient
                                              ↓
                                         (parallel workers)
                                              ↓
                                         rate limiting
                                              ↓
                                         retry logic
"""

from .client import LLMBatchClient
from .stats import BatchStatsTracker
from .processor import LLMBatchProcessor
from .progress import create_progress_handler
from .schemas import (
    RequestPhase,
    RequestStatus,
    BatchStats,
    LLMBatchConfig,
)

__all__ = [
    'LLMBatchProcessor',
    'LLMBatchConfig',
    'LLMBatchClient',
    'BatchStats',
    'BatchStatsTracker',
    'RequestPhase',
    'RequestStatus',
    'create_progress_handler',
]
