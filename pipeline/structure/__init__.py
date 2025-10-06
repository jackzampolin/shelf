"""
Structure Stage - Phase 1 Implementation (Session 1)

NEW 2-Phase Architecture:
- Phase 1: Sliding window extraction (this session)
- Phase 2: Assembly & chunking (future session)

Current status: Agents implemented, orchestrator TODO
"""

# For now, create a stub to avoid circular import issues
# This will be replaced with the full orchestrator in Session 2

class BookStructurer:
    """Stub - will be implemented in Session 2."""

    def __init__(self, scan_id, storage_root=None):
        raise NotImplementedError(
            "BookStructurer not yet implemented. "
            "Session 1 implemented agents only. "
            "Use agents directly from pipeline.structure.agents"
        )

    def process_book(self):
        raise NotImplementedError("See __init__ message")


# Export agents for use in tests
from .agents import (
    extract_batch,
    verify_extraction,
    reconcile_overlaps
)

__all__ = [
    'BookStructurer',
    'extract_batch',
    'verify_extraction',
    'reconcile_overlaps'
]
