"""
Link-toc stage data access.

Ground truth from disk (ADR 001).
One concept per file (ADR 006).
"""

from typing import Optional, Dict, Any, List
from infra.pipeline.storage.book_storage import BookStorage


def get_link_toc_data(storage: BookStorage) -> Optional[Dict[str, Any]]:
    """
    Load link-toc data from disk.

    Returns:
        Dict with:
        - entries: list of linked TOC entries
        - metadata: {total_entries, linked_entries, unlinked_entries, avg_link_confidence}
        - stats: {total_cost_usd, total_time_seconds, avg_iterations_per_entry}

    Returns None if linked_toc.json doesn't exist (stage not run yet).
    """
    link_toc_storage = storage.stage("link-toc")
    linked_toc_path = link_toc_storage.output_dir / "linked_toc.json"

    if not linked_toc_path.exists():
        return None

    linked_toc_data = link_toc_storage.load_file("linked_toc.json")

    if not linked_toc_data:
        return None

    return {
        'entries': linked_toc_data.get('entries', []),
        'metadata': {
            'total_entries': linked_toc_data.get('total_entries', 0),
            'linked_entries': linked_toc_data.get('linked_entries', 0),
            'unlinked_entries': linked_toc_data.get('unlinked_entries', 0),
            'avg_link_confidence': linked_toc_data.get('avg_link_confidence', 0.0),
        },
        'stats': {
            'total_cost_usd': linked_toc_data.get('total_cost_usd', 0.0),
            'total_time_seconds': linked_toc_data.get('total_time_seconds', 0.0),
            'avg_iterations_per_entry': linked_toc_data.get('avg_iterations_per_entry', 0.0),
        }
    }


def get_linked_entries_tree(storage: BookStorage) -> Optional[List[Dict[str, Any]]]:
    """
    Get linked TOC entries organized as a hierarchical tree structure.

    Returns:
        List of entries with hierarchy preserved, or None if data doesn't exist.
        Each entry contains:
        - title: str
        - level: int (1-3)
        - scan_page: int or None
        - link_confidence: float
        - printed_page_number: str or None
    """
    data = get_link_toc_data(storage)
    if not data:
        return None

    entries = data.get('entries', [])
    if not entries:
        return []

    # Filter out None entries (can happen during incremental processing)
    return [entry for entry in entries if entry is not None]
