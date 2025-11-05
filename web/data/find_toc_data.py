"""
Find-toc stage data access.

Ground truth from disk (ADR 001).
One concept per file (ADR 006).
"""

from typing import Optional, Dict, Any, List
from infra.storage.book_storage import BookStorage


def get_find_toc_data(storage: BookStorage) -> Optional[Dict[str, Any]]:
    """
    Load find-toc finder result from disk.

    Returns:
        Dict with:
        - toc_found: bool
        - toc_page_range: {start_page, end_page} or None
        - confidence: float
        - search_strategy_used: str
        - pages_checked: int
        - reasoning: str
        - structure_notes: dict[page_num, note] or None
        - structure_summary: {total_levels, level_patterns, consistency_notes} or None

    Returns None if finder_result.json doesn't exist (stage not run yet).
    """
    find_toc_storage = storage.stage("find-toc")
    finder_path = find_toc_storage.output_dir / "finder_result.json"

    if not finder_path.exists():
        return None

    finder_result = find_toc_storage.load_file("finder_result.json")

    if not finder_result:
        return None

    return {
        'toc_found': finder_result.get('toc_found', False),
        'toc_page_range': finder_result.get('toc_page_range'),
        'confidence': finder_result.get('confidence', 0.0),
        'search_strategy_used': finder_result.get('search_strategy_used', 'unknown'),
        'pages_checked': finder_result.get('pages_checked', 0),
        'reasoning': finder_result.get('reasoning', ''),
        'structure_notes': finder_result.get('structure_notes'),
        'structure_summary': finder_result.get('structure_summary'),
    }


def get_toc_page_numbers(storage: BookStorage) -> List[int]:
    """
    Get list of page numbers where TOC appears.

    Returns empty list if find-toc not run or TOC not found.
    """
    finder_data = get_find_toc_data(storage)

    if not finder_data or not finder_data['toc_found']:
        return []

    page_range = finder_data.get('toc_page_range')
    if not page_range:
        return []

    start = page_range.get('start_page', 0)
    end = page_range.get('end_page', 0)

    if start > 0 and end >= start:
        return list(range(start, end + 1))

    return []
