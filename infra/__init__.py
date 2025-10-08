"""
Infrastructure for Scanshelf Pipeline

Core infrastructure modules that all pipeline stages depend on:
- Config: Configuration management (env vars, API keys, storage paths)
- Checkpoint: Resume capability and progress tracking
- Logger: Structured logging and console output
- LLM Client: API calls with retry logic and cost tracking
- Pricing: Cost calculation and caching
- Parallel: Unified parallelization with progress tracking and rate limiting
- Metadata: Scan metadata management utilities
"""

from infra.config import Config
from infra.checkpoint import CheckpointManager
from infra.logger import PipelineLogger
from infra.llm_client import LLMClient
from infra.pricing import PricingCache, CostCalculator, calculate_cost
from infra.parallel import ParallelProcessor, RateLimiter
from infra.metadata import (
    update_book_metadata,
    get_latest_processing_record,
    get_scan_total_cost,
    get_scan_models,
    format_processing_summary
)

__all__ = [
    "Config",
    "CheckpointManager",
    "PipelineLogger",
    "LLMClient",
    "PricingCache",
    "CostCalculator",
    "calculate_cost",
    "ParallelProcessor",
    "RateLimiter",
    "update_book_metadata",
    "get_latest_processing_record",
    "get_scan_total_cost",
    "get_scan_models",
    "format_processing_summary",
]
