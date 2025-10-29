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
    Enhanced with PSM analysis status and overall progress.
    """
    books = _adapter.find_all_books()

    # Add PSM analysis status and overall progress for each book
    for book in books:
        book['psm_analysis'] = get_psm_analysis_status(book['scan_id'])
        book['overall_progress'] = calculate_overall_progress(book)

    # Sort by overall progress (most complete first)
    books.sort(key=lambda b: b['overall_progress'], reverse=True)

    return books


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


def get_winning_ocr_data(scan_id: str, page_num: int) -> Optional[Dict]:
    """Load OCR data from the winning PSM for a specific page.

    Uses psm_selection.json to determine which PSM won for this page,
    then loads from that PSM's subdirectory.

    Returns:
        {
            "data": {...},         # OCRPageOutput from winning PSM
            "winning_psm": 4,      # Which PSM won
            "available_psms": [3, 4, 6],  # All PSMs with data
            "reason": "highest_confidence"  # Why this PSM won
        }
        or None if no data available
    """
    ocr_dir = LIBRARY_ROOT / scan_id / "ocr"

    # Load PSM selection
    selection_file = ocr_dir / "psm_selection.json"
    if not selection_file.exists():
        return None

    try:
        with open(selection_file) as f:
            selection_data = json.load(f)

        # Get winning PSM for this page
        page_selections = selection_data.get("page_selections", {})
        winning_psm = page_selections.get(str(page_num))

        if winning_psm is None:
            return None

        # Load data from winning PSM
        winning_psm_file = ocr_dir / f"psm{winning_psm}" / f"page_{page_num:04d}.json"
        if not winning_psm_file.exists():
            return None

        with open(winning_psm_file) as f:
            ocr_data = json.load(f)

        # Find which PSMs have data for this page
        available_psms = []
        for psm in [3, 4, 6]:
            psm_file = ocr_dir / f"psm{psm}" / f"page_{page_num:04d}.json"
            if psm_file.exists():
                available_psms.append(psm)

        return {
            "data": ocr_data,
            "winning_psm": winning_psm,
            "available_psms": available_psms,
            "selection_criteria": selection_data.get("selection_criteria", "unknown")
        }
    except Exception:
        return None


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


def get_psm_selection(scan_id: str) -> Optional[Dict[str, Any]]:
    """Load PSM selection data for a book.

    Returns psm_selection.json which maps each page to its winning PSM mode.

    Returns:
        {
            "selection_criteria": "highest_mean_confidence",
            "page_selections": {1: 4, 2: 6, ...},
            "summary": {"psm3_wins": 45, "psm4_wins": 312, "psm6_wins": 90}
        }
        or None if file doesn't exist
    """
    selection_file = LIBRARY_ROOT / scan_id / "ocr" / "psm_selection.json"
    if not selection_file.exists():
        return None

    try:
        with open(selection_file) as f:
            return json.load(f)
    except Exception:
        return None


def get_psm_reports(scan_id: str) -> Optional[Dict[str, Any]]:
    """Load PSM analysis reports for a book.

    Combines confidence and agreement reports into a single structure.

    Returns:
        {
            "confidence": {...},  # psm_confidence_report.json content
            "agreement": {...}    # psm_agreement_report.json content
        }
        or None if files don't exist
    """
    ocr_dir = LIBRARY_ROOT / scan_id / "ocr"
    confidence_file = ocr_dir / "psm_confidence_report.json"
    agreement_file = ocr_dir / "psm_agreement_report.json"

    if not confidence_file.exists() and not agreement_file.exists():
        return None

    reports = {}

    try:
        if confidence_file.exists():
            with open(confidence_file) as f:
                reports["confidence"] = json.load(f)

        if agreement_file.exists():
            with open(agreement_file) as f:
                reports["agreement"] = json.load(f)

        return reports if reports else None
    except Exception:
        return None


def get_psm_analysis_status(scan_id: str) -> Dict[str, Any]:
    """Check PSM analysis completeness for a book.

    Returns:
        {
            "has_selection": bool,
            "has_confidence": bool,
            "has_agreement": bool,
            "status": "complete" | "partial" | "none"
        }
    """
    ocr_dir = LIBRARY_ROOT / scan_id / "ocr"

    has_selection = (ocr_dir / "psm_selection.json").exists()
    has_confidence = (ocr_dir / "psm_confidence_report.json").exists()
    has_agreement = (ocr_dir / "psm_agreement_report.json").exists()

    # Determine overall status
    if has_selection and has_confidence and has_agreement:
        status = "complete"
    elif has_selection or has_confidence or has_agreement:
        status = "partial"
    else:
        status = "none"

    return {
        "has_selection": has_selection,
        "has_confidence": has_confidence,
        "has_agreement": has_agreement,
        "status": status
    }


def calculate_overall_progress(book: Dict[str, Any]) -> float:
    """Calculate overall pipeline progress for a book (0-100).

    Weighted by stage importance:
    - OCR: 30%
    - Corrected: 25%
    - Labels: 20%
    - Merged: 15%
    - ToC: 10%

    Returns:
        Progress percentage (0-100)
    """
    weights = {
        "ocr": 0.30,
        "corrected": 0.25,
        "labels": 0.20,
        "merged": 0.15,
        "toc": 0.10
    }

    progress = 0.0

    # Calculate weighted progress for each stage
    for stage in ["ocr", "corrected", "labels", "merged"]:
        stage_data = book.get(stage, {})
        total = stage_data.get("total", 0)
        completed = stage_data.get("completed", 0)

        if total > 0:
            stage_progress = (completed / total) * 100 * weights[stage]
            progress += stage_progress

    # ToC is binary (complete or not)
    if book.get("has_toc", False):
        progress += 100 * weights["toc"]

    return round(progress, 1)
