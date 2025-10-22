"""
Storage subsystem for book data and state management.

Provides:
- BookStorage: Unified storage manager with stage-specific views
- CheckpointManager: File-based progress tracking and resume capability
- Metadata utilities: Processing history and cost tracking
"""

from infra.storage.book_storage import BookStorage
from infra.storage.checkpoint import CheckpointManager
from infra.storage.metadata import (
    update_book_metadata,
    get_latest_processing_record,
    get_scan_total_cost,
    get_scan_models,
    format_processing_summary
)

__all__ = [
    "BookStorage",
    "CheckpointManager",
    "update_book_metadata",
    "get_latest_processing_record",
    "get_scan_total_cost",
    "get_scan_models",
    "format_processing_summary",
]
