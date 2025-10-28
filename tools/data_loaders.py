"""
Data loading utilities for Shelf Viewer.

Handles all data access operations including:
- Loading book metadata and stage status
- Loading page data from JSON files
- Loading and parsing log files
- Loading CSV reports and calculating statistics

REFACTORED: Now uses pipeline storage abstractions via storage_adapter.py
instead of manual file access. This provides:
- Type-safe schema validation
- Thread-safe operations
- Consistent with pipeline behavior
- No code duplication
"""

import csv
import json
import os
from pathlib import Path
from typing import Optional, List, Dict, Any

from PIL import Image
from storage_adapter import ViewerStorageAdapter

# Get library root from env or default
LIBRARY_ROOT = Path(os.getenv("BOOK_STORAGE_ROOT", "~/Documents/book_scans")).expanduser()

# Global storage adapter instance
_adapter = ViewerStorageAdapter(storage_root=LIBRARY_ROOT)


def get_stage_status(book_dir: Path, stage: str) -> Dict[str, Any]:
    """Get checkpoint status for a stage.

    REFACTORED: Uses storage adapter instead of manual checkpoint parsing.

    Returns:
        - status: 'complete', 'in_progress', 'not_started', 'no_data'
        - completed: number of completed pages
        - total: total number of pages
    """
    # Extract scan_id from book_dir
    scan_id = book_dir.name
    return _adapter.get_stage_status(scan_id, stage)


def find_all_books() -> List[Dict[str, Any]]:
    """Find all books in library with their stage statuses.

    REFACTORED: Uses storage adapter for all data access.
    """
    return _adapter.find_all_books()


def get_page_image_path(scan_id: str, page_num: int) -> Optional[Path]:
    """Get path to source image for a page.

    REFACTORED: Uses storage adapter which provides proper path construction.
    """
    return _adapter.get_page_image_path(scan_id, page_num)


def get_stage_data(scan_id: str, stage: str, page_num: int) -> Optional[Dict]:
    """Load JSON data for a specific stage and page.

    REFACTORED: Uses storage adapter. Can add schema validation in future.
    """
    return _adapter.get_page_data(scan_id, stage, page_num)


def get_book_pages(scan_id: str) -> List[int]:
    """Get list of page numbers for a book.

    REFACTORED: Uses storage adapter.
    """
    return _adapter.get_book_pages(scan_id)


def get_page_image_dimensions(scan_id: str, page_num: int) -> tuple[int, int]:
    """Get image dimensions for a page.

    REFACTORED: Uses storage adapter.
    """
    return _adapter.get_page_image_dimensions(scan_id, page_num)


def get_stage_logs(scan_id: str, stage: str, level_filter: Optional[str] = None,
                   search: Optional[str] = None, limit: int = 50) -> List[Dict]:
    """Load and parse the latest log file for a stage.

    REFACTORED: Uses storage adapter to get log file path.

    Args:
        scan_id: Book identifier
        stage: Stage name (ocr, corrected, labels, merged, build_structure)
        level_filter: Filter by log level (INFO, ERROR, WARNING)
        search: Search in message text
        limit: Max number of entries to return

    Returns:
        List of log entries (parsed JSON objects)
    """
    # Get latest log file via adapter
    latest_log = _adapter.get_latest_log_file(scan_id, stage)
    if not latest_log:
        return []

    # Parse JSONL
    entries = []
    try:
        with open(latest_log) as f:
            for line in f:
                try:
                    entry = json.loads(line)

                    # Apply filters
                    if level_filter and entry.get("level") != level_filter:
                        continue
                    if search and search.lower() not in entry.get("message", "").lower():
                        continue

                    entries.append(entry)
                except json.JSONDecodeError:
                    continue
    except Exception:
        return []

    # Return latest entries first, limited
    return entries[-limit:] if len(entries) > limit else entries


def get_stage_stats(scan_id: str, stage: str) -> Optional[Dict[str, Any]]:
    """Load stats from report.csv for a stage.

    REFACTORED: Uses storage adapter to get report path.

    Returns:
        Dict with aggregated stats or None if no report exists
    """
    from stats_calculator import (
        calculate_ocr_stats,
        calculate_corrected_stats,
        calculate_labels_stats
    )

    # Get report path via adapter
    report_path = _adapter.get_stage_report_path(scan_id, stage)
    if not report_path:
        return None

    try:
        with open(report_path) as f:
            rows = list(csv.DictReader(f))

        if not rows:
            return None

        # Calculate common stats
        total_pages = len(rows)

        # Stage-specific processing
        if stage == "ocr":
            return calculate_ocr_stats(rows, total_pages)
        elif stage == "corrected":
            return calculate_corrected_stats(rows, total_pages)
        elif stage == "labels":
            return calculate_labels_stats(rows, total_pages)
        else:
            # Generic stats for other stages
            confidences = []
            for row in rows:
                if 'avg_confidence' in row and row['avg_confidence']:
                    try:
                        confidences.append(float(row['avg_confidence']))
                    except ValueError:
                        pass

            avg_confidence = sum(confidences) / len(confidences) if confidences else None

            return {
                "total_pages": total_pages,
                "avg_confidence": avg_confidence,
                "rows": rows[:10],  # First 10 for preview
            }
    except Exception:
        return None
