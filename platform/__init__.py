"""
Platform Infrastructure for Scanshelf Pipeline

Core infrastructure modules that all pipeline stages depend on:
- Config: Configuration management (env vars, API keys, storage paths)
- Checkpoint: Resume capability and progress tracking
- Logger: Structured logging and console output
- LLM Client: API calls with retry logic and cost tracking
- Pricing: Token counting and cost calculation
- Parallel: Unified parallelization with progress tracking and rate limiting
- Metadata: Scan metadata management utilities
"""

from platform.config import Config
from platform.checkpoint import Checkpoint
from platform.logger import PipelineLogger
from platform.llm_client import LLMClient
from platform.pricing import estimate_cost, count_tokens
from platform.parallel import ParallelProcessor, RateLimiter
from platform.metadata import (
    update_book_metadata,
    get_latest_processing_record,
    get_scan_total_cost,
    get_scan_models,
    format_processing_summary
)

__all__ = [
    "Config",
    "Checkpoint",
    "PipelineLogger",
    "LLMClient",
    "estimate_cost",
    "count_tokens",
    "ParallelProcessor",
    "RateLimiter",
    "update_book_metadata",
    "get_latest_processing_record",
    "get_scan_total_cost",
    "get_scan_models",
    "format_processing_summary",
]
