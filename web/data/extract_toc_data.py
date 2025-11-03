"""
Extract-toc stage data access.

Ground truth from disk (ADR 001).
One concept per file (ADR 006).
"""

from typing import Optional, Dict, Any, List
from infra.storage.book_storage import BookStorage


def get_extract_toc_data(storage: BookStorage) -> Optional[Dict[str, Any]]:
    """
    Load extract-toc data from disk.

    Returns:
        Dict with:
        - toc_found: bool
        - page_range: {start_page, end_page} (if found)
        - toc_entries: list of entries (if extracted)
        - toc_metadata: {total_chapters, total_sections, confidence}

    Returns None if finder_result.json doesn't exist (stage not run yet).
    """
    stage_storage = storage.stage("extract-toc")

    # Check if finder has run
    finder_path = stage_storage.output_dir / "finder_result.json"
    if not finder_path.exists():
        return None

    # Load finder result
    finder_result = stage_storage.load_file("finder_result.json")

    data = {
        'toc_found': finder_result.get('toc_found', False),
        'page_range': None,
        'toc_entries': [],
        'toc_metadata': None,
    }

    if data['toc_found']:
        data['page_range'] = finder_result.get('toc_page_range', {})

    # Load final TOC if it exists
    toc_path = stage_storage.output_dir / "toc.json"
    if toc_path.exists():
        toc_data = stage_storage.load_file("toc.json")

        if toc_data and toc_data.get('toc'):
            toc = toc_data['toc']
            data['toc_entries'] = toc.get('entries', [])
            data['toc_metadata'] = {
                'total_chapters': toc.get('total_chapters', 0),
                'total_sections': toc.get('total_sections', 0),
                'parsing_confidence': toc.get('parsing_confidence', 0.0),
                'notes': toc.get('notes', []),
            }

    return data


def get_toc_page_numbers(storage: BookStorage) -> List[int]:
    """
    Get list of page numbers where TOC appears.

    Returns empty list if TOC not found or stage not run.
    """
    data = get_extract_toc_data(storage)

    if not data or not data['toc_found'] or not data['page_range']:
        return []

    page_range = data['page_range']
    start = page_range.get('start_page', 0)
    end = page_range.get('end_page', 0)

    if start > 0 and end >= start:
        return list(range(start, end + 1))

    return []
