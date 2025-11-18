"""
Extract-toc stage data access.

Ground truth from disk (ADR 001).
One concept per file (ADR 006).
"""

from typing import Optional, Dict, Any, List
from infra.pipeline.storage.book_storage import BookStorage


def get_extract_toc_data(storage: BookStorage) -> Optional[Dict[str, Any]]:
    """
    Load extract-toc data from disk.

    Returns:
        Dict with:
        - toc_entries: list of entries
        - toc_metadata: {total_chapters, total_sections, confidence, notes}

    Returns None if toc.json doesn't exist (stage not run yet).
    """
    extract_toc_storage = storage.stage("extract-toc")
    toc_path = extract_toc_storage.output_dir / "toc.json"

    if not toc_path.exists():
        return None

    toc_data = extract_toc_storage.load_file("toc.json")

    if not toc_data or not toc_data.get('toc'):
        return None

    toc = toc_data['toc']

    return {
        'toc_entries': toc.get('entries', []),
        'toc_metadata': {
            'total_chapters': toc.get('total_chapters', 0),
            'total_sections': toc.get('total_sections', 0),
            'parsing_confidence': toc.get('parsing_confidence', 0.0),
            'notes': toc.get('notes', []),
        }
    }


def get_toc_page_numbers(storage: BookStorage) -> List[int]:
    """
    Get list of page numbers where TOC appears.

    Reads from extract-toc stage (find phase output).
    Returns empty list if find phase not run or TOC not found.
    """
    extract_toc_storage = storage.stage("extract-toc")
    finder_path = extract_toc_storage.output_dir / "finder_result.json"

    if not finder_path.exists():
        return []

    finder_result = extract_toc_storage.load_file("finder_result.json")

    if not finder_result.get('toc_found'):
        return []

    page_range = finder_result.get('toc_page_range', {})
    start = page_range.get('start_page', 0)
    end = page_range.get('end_page', 0)

    if start > 0 and end >= start:
        return list(range(start, end + 1))

    return []


def get_validation_data(storage: BookStorage) -> Optional[Dict[str, Any]]:
    """
    Load validation corrections and analysis from extract-toc.

    Returns:
        Dict with:
        - corrections: list of corrections applied
        - analysis: {toc_quality, patterns_found, observations}
        - validation_stats: {entries_reviewed, corrections_proposed}

    Returns None if corrections.json doesn't exist.
    """
    extract_toc_storage = storage.stage("extract-toc")
    corrections_path = extract_toc_storage.output_dir / "corrections.json"

    if not corrections_path.exists():
        return None

    return extract_toc_storage.load_file("corrections.json")
