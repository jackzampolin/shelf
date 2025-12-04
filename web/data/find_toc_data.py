from typing import Optional, Dict, Any, List
from infra.pipeline.storage.book_storage import BookStorage


def _get_find_toc_data(storage: BookStorage) -> Optional[Dict[str, Any]]:
    extract_toc_storage = storage.stage("extract-toc")
    finder_path = extract_toc_storage.output_dir / "finder_result.json"

    if not finder_path.exists():
        return None

    finder_result = extract_toc_storage.load_file("finder_result.json")

    if not finder_result:
        return None

    return {
        'toc_found': finder_result.get('toc_found', False),
        'toc_page_range': finder_result.get('toc_page_range'),
    }


def get_toc_page_numbers(storage: BookStorage) -> List[int]:
    finder_data = _get_find_toc_data(storage)

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
