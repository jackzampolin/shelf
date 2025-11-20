"""
Link-toc stage data access.

Ground truth from disk (ADR 001).
One concept per file (ADR 006).
"""

from typing import Optional, Dict, Any, List
from infra.pipeline.storage.book_storage import BookStorage


def get_enriched_toc_data(storage: BookStorage) -> Optional[Dict[str, Any]]:
    """
    Load enriched ToC data from Phase 4 (merge).

    Returns enriched_toc.json if it exists, containing:
    - entries: List[EnrichedToCEntry] with ToC + discovered headings
    - original_toc_count: int
    - discovered_count: int
    - total_entries: int
    - pattern_confidence: float
    - pattern_description: str
    """
    link_toc_storage = storage.stage("link-toc")
    enriched_path = link_toc_storage.output_dir / "enriched_toc.json"

    if not enriched_path.exists():
        return None

    return link_toc_storage.load_file("enriched_toc.json")


def get_pattern_analysis(storage: BookStorage) -> Optional[Dict[str, Any]]:
    """
    Load pattern analysis from Phase 2.

    Returns pattern_analysis.json if it exists, containing:
    - pattern_description: str
    - expected_relationship: str (fill_gaps, sections_under_chapters, unknown)
    - body_range: [int, int]
    - toc_structure: dict
    - discovered_structure: dict
    - candidate_headings: List[CandidateHeading]
    - confidence: float
    - reasoning: str
    """
    link_toc_storage = storage.stage("link-toc")
    pattern_path = link_toc_storage.output_dir / "pattern" / "pattern_analysis.json"

    if not pattern_path.exists():
        return None

    return link_toc_storage.load_file("pattern/pattern_analysis.json")


def get_evaluation_summary(storage: BookStorage) -> Optional[Dict[str, Any]]:
    """
    Load evaluation summary from Phase 3.

    Returns dict with:
    - total_evaluated: int
    - included_count: int
    - excluded_count: int
    - decisions: List[HeadingDecision] (all decisions)
    """
    link_toc_storage = storage.stage("link-toc")
    eval_dir = link_toc_storage.output_dir / "evaluation"

    if not eval_dir.exists():
        return None

    decision_files = sorted(eval_dir.glob("heading_*.json"))
    if not decision_files:
        return None

    decisions = []
    for decision_file in decision_files:
        decision_data = link_toc_storage.load_file(f"evaluation/{decision_file.name}")
        if decision_data:
            decisions.append(decision_data)

    included = sum(1 for d in decisions if d.get('include', False))
    excluded = len(decisions) - included

    return {
        'total_evaluated': len(decisions),
        'included_count': included,
        'excluded_count': excluded,
        'decisions': decisions
    }


def get_link_toc_data(storage: BookStorage) -> Optional[Dict[str, Any]]:
    """
    Load link-toc data with progressive enhancement.

    Priority:
    1. Try enriched_toc.json (Phase 4 - final output)
    2. Fall back to linked_toc.json (Phase 1 only)

    Returns:
        Dict with:
        - entries: list of entries (enriched or linked)
        - metadata: {total_entries, linked_entries, unlinked_entries, ...}
        - stats: {total_cost_usd, total_time_seconds}
        - is_enriched: bool (True if enriched ToC, False if linked only)
        - pattern_analysis: dict or None (Phase 2 data)
        - evaluation_summary: dict or None (Phase 3 data)
    """
    link_toc_storage = storage.stage("link-toc")

    # Try enriched ToC first (Phase 4 output)
    enriched_data = get_enriched_toc_data(storage)

    if enriched_data:
        # Load Phase 1 metrics from linked_toc.json for cost/time
        linked_toc_data = link_toc_storage.load_file("linked_toc.json")

        return {
            'entries': enriched_data.get('entries', []),
            'metadata': {
                'total_entries': enriched_data.get('total_entries', 0),
                'original_toc_count': enriched_data.get('original_toc_count', 0),
                'discovered_count': enriched_data.get('discovered_count', 0),
                'pattern_confidence': enriched_data.get('pattern_confidence', 0.0),
                'pattern_description': enriched_data.get('pattern_description', ''),
            },
            'stats': {
                'total_cost_usd': linked_toc_data.get('total_cost_usd', 0.0) if linked_toc_data else 0.0,
                'total_time_seconds': linked_toc_data.get('total_time_seconds', 0.0) if linked_toc_data else 0.0,
            },
            'is_enriched': True,
            'pattern_analysis': get_pattern_analysis(storage),
            'evaluation_summary': get_evaluation_summary(storage),
        }

    # Fall back to linked ToC (Phase 1 only)
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
        },
        'stats': {
            'total_cost_usd': linked_toc_data.get('total_cost_usd', 0.0),
            'total_time_seconds': linked_toc_data.get('total_time_seconds', 0.0),
        },
        'is_enriched': False,
        'pattern_analysis': None,
        'evaluation_summary': None,
    }


def get_linked_entries_tree(storage: BookStorage) -> Optional[List[Dict[str, Any]]]:
    """
    Get entries for display.

    Progressive enhancement:
    - Returns enriched ToC entries if available (Phase 4)
    - Falls back to linked ToC entries (Phase 1)

    Returns:
        List of entries, or None if data doesn't exist.
    """
    data = get_link_toc_data(storage)
    if not data:
        return None

    entries = data.get('entries', [])
    if not entries:
        return []

    # Filter out None entries (can happen during incremental processing)
    return [entry for entry in entries if entry is not None]
