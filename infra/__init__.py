"""
Infrastructure for Scanshelf Pipeline

Organized into logical subsystems:
- storage: Book data storage, metrics tracking, metadata
- llm: LLM API integration, batching, cost tracking
- pipeline: Logging, progress tracking
- utils: Shared utilities (PDF, image processing)
- config: Environment configuration (stays at root)
"""

# Core configuration (used everywhere)
from infra.config import Config

# Storage subsystem
from infra.storage import (
    BookStorage,
    MetricsManager,
    update_book_metadata,
    get_latest_processing_record,
    get_scan_total_cost,
    get_scan_models,
    format_processing_summary
)

# LLM subsystem
from infra.llm import (
    LLMClient,
    LLMBatchClient,
    LLMRequest,
    LLMResult,
    LLMEvent,
    EventData,
    RequestPhase,
    RequestStatus,
    CompletedStatus,
    BatchStats,
    PricingCache,
    CostCalculator,
    calculate_cost,
    RateLimiter
)

# Pipeline subsystem
from infra.pipeline import (
    PipelineLogger,
    create_logger,
    ProgressBar
)

# Utilities
from infra.utils.pdf import (
    downsample_for_vision,
    get_page_from_book,
    image_to_base64
)

__all__ = [
    # Config
    "Config",

    # Storage
    "BookStorage",
    "MetricsManager",
    "update_book_metadata",
    "get_latest_processing_record",
    "get_scan_total_cost",
    "get_scan_models",
    "format_processing_summary",

    # LLM
    "LLMClient",
    "LLMBatchClient",
    "LLMRequest",
    "LLMResult",
    "LLMEvent",
    "EventData",
    "RequestPhase",
    "RequestStatus",
    "CompletedStatus",
    "BatchStats",
    "PricingCache",
    "CostCalculator",
    "calculate_cost",
    "RateLimiter",

    # Pipeline
    "PipelineLogger",
    "create_logger",
    "ProgressBar",

    # Utils
    "downsample_for_vision",
    "get_page_from_book",
    "image_to_base64",
]
