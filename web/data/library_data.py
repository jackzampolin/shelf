"""
Library-level data access functions.

Mirrors cli/namespace_library.py data access patterns.
Ground truth from disk (ADR 001).
"""

from typing import List, Dict, Any
from pathlib import Path

from infra.pipeline.storage.library import Library
from infra.pipeline.storage.book_storage import BookStorage
from cli.constants import STAGE_NAMES
from web.data.status_reader import get_stage_status_from_disk
from web.data.ocr_pages_data import get_ocr_aggregate_status, get_metadata_status


def get_all_books(storage_root: Path) -> List[Dict[str, Any]]:
    """
    Get all books in library with stage status and metrics.

    Mirrors cli/namespace_library.py::cmd_list() data access.
    Each stage status comes directly from calling that stage's get_status() method.

    Returns:
        List of book dicts with:
        - scan_id: str
        - metadata: dict (title, author, year, pages)
        - stages: dict[stage_name -> {status, cost_usd, runtime_seconds}]
        - total_cost_usd: float
        - total_runtime_seconds: float
    """
    library = Library(storage_root=storage_root)
    scans = library.list_all_scans()

    if not scans:
        return []

    books = []

    for scan in scans:
        scan_id = scan['scan_id']
        storage = library.get_book_storage(scan_id)

        # Check if metadata has been extracted
        metadata_info = get_metadata_status(storage)
        has_metadata = metadata_info is not None

        book = {
            'scan_id': scan_id,
            'metadata': {
                'title': metadata_info['title'] if has_metadata else scan.get('title', 'Unknown'),
                'author': ', '.join(metadata_info['authors']) if has_metadata and metadata_info.get('authors') else scan.get('author', 'Unknown'),
                'year': scan.get('year', 'Unknown'),
                'pages': scan.get('pages', 0),
            },
            'has_metadata': has_metadata,
            'stages': {},
            'total_cost_usd': 0.0,
            'total_runtime_seconds': 0.0,
        }

        # Get status for each stage (read directly from disk)
        # Special handling for OCR stages - aggregate them into one "ocr-pages" entry
        ocr_aggregate = get_ocr_aggregate_status(storage)
        book['stages']['ocr-pages'] = {
            'status': ocr_aggregate['status'],
            'cost_usd': ocr_aggregate['total_cost_usd'],
            'runtime_seconds': ocr_aggregate['total_runtime_seconds'],
        }
        book['total_cost_usd'] += ocr_aggregate['total_cost_usd']
        book['total_runtime_seconds'] += ocr_aggregate['total_runtime_seconds']

        # Get status for non-OCR stages
        for stage_name in STAGE_NAMES:
            if stage_name == 'ocr-pages':
                continue  # Skip - already handled above by get_ocr_aggregate_status

            status = get_stage_status_from_disk(storage, stage_name)

            if status:
                stage_status = status.get('status', 'not_started')
                metrics = status.get('metrics', {})
                stage_cost = metrics.get('total_cost_usd', 0.0)
                stage_runtime = metrics.get('stage_runtime_seconds', 0.0)

                book['stages'][stage_name] = {
                    'status': stage_status,
                    'cost_usd': stage_cost,
                    'runtime_seconds': stage_runtime,
                }

                book['total_cost_usd'] += stage_cost
                book['total_runtime_seconds'] += stage_runtime
            else:
                book['stages'][stage_name] = {
                    'status': 'not_started',
                    'cost_usd': 0.0,
                    'runtime_seconds': 0.0,
                }

        books.append(book)

    # Sort by scan_id (alphabetical)
    books.sort(key=lambda b: b['scan_id'])

    return books
