"""
Data loading utilities for Shelf Viewer.

Handles all data access operations including:
- Loading book metadata and stage status
- Loading page data from JSON files
- Loading and parsing log files
- Loading CSV reports and calculating statistics
"""

import csv
import json
import os
from pathlib import Path
from typing import Optional, List, Dict, Any

from PIL import Image

# Get library root from env or default
LIBRARY_ROOT = Path(os.getenv("BOOK_STORAGE_ROOT", "~/Documents/book_scans")).expanduser()


def get_stage_status(book_dir: Path, stage: str) -> Dict[str, Any]:
    """Get checkpoint status for a stage.

    Returns:
        - status: 'complete', 'in_progress', 'not_started', 'no_data'
        - completed: number of completed pages
        - total: total number of pages
    """
    stage_dir = book_dir / stage
    if not stage_dir.exists():
        return {"status": "no_data", "completed": 0, "total": 0}

    checkpoint_path = stage_dir / ".checkpoint"
    if not checkpoint_path.exists():
        return {"status": "not_started", "completed": 0, "total": 0}

    try:
        with open(checkpoint_path) as f:
            checkpoint = json.load(f)

        total = len(checkpoint.get("page_metrics", {}))
        if total == 0:
            return {"status": "not_started", "completed": 0, "total": 0}

        status = checkpoint.get("status", "unknown")
        if status == "completed":
            return {"status": "complete", "completed": total, "total": total}
        else:
            # Count completed pages in page_metrics
            completed = sum(
                1 for metrics in checkpoint.get("page_metrics", {}).values()
                if metrics.get("status") == "completed"
            )
            if completed == 0:
                return {"status": "not_started", "completed": 0, "total": total}
            else:
                return {"status": "in_progress", "completed": completed, "total": total}
    except Exception:
        return {"status": "not_started", "completed": 0, "total": 0}


def find_all_books() -> List[Dict[str, Any]]:
    """Find all books in library with their stage statuses."""
    books = []
    for book_dir in sorted(LIBRARY_ROOT.iterdir()):
        if not book_dir.is_dir() or book_dir.name.startswith('.'):
            continue

        book_info = {
            "scan_id": book_dir.name,
            "has_source": (book_dir / "source").exists(),
        }

        # Get status for each pipeline stage
        book_info["ocr"] = get_stage_status(book_dir, "ocr")
        book_info["corrected"] = get_stage_status(book_dir, "corrected")
        book_info["labels"] = get_stage_status(book_dir, "labels")
        book_info["merged"] = get_stage_status(book_dir, "merged")

        # Check if ToC has actual data
        toc_path = book_dir / "build_structure" / "toc.json"
        if toc_path.exists():
            with open(toc_path) as f:
                toc_data = json.load(f)
            if not ("note" in toc_data and "No ToC found" in toc_data["note"]):
                book_info["has_toc"] = True
            else:
                book_info["has_toc"] = False
        else:
            book_info["has_toc"] = False

        books.append(book_info)

    return books


def get_page_image_path(scan_id: str, page_num: int) -> Optional[Path]:
    """Get path to source image for a page."""
    # Validate scan_id doesn't contain path traversal
    if '..' in scan_id or '/' in scan_id:
        return None

    # Validate page_num is reasonable
    if page_num < 1 or page_num > 9999:
        return None

    # Check for PNG first
    img_path = LIBRARY_ROOT / scan_id / "source" / f"page_{page_num:04d}.png"
    if img_path.exists():
        return img_path

    # Try JPG
    img_path = LIBRARY_ROOT / scan_id / "source" / f"page_{page_num:04d}.jpg"
    if img_path.exists():
        return img_path

    return None


def get_stage_data(scan_id: str, stage: str, page_num: int) -> Optional[Dict]:
    """Load JSON data for a specific stage and page."""
    data_path = LIBRARY_ROOT / scan_id / stage / f"page_{page_num:04d}.json"
    if not data_path.exists():
        return None
    with open(data_path) as f:
        return json.load(f)


def get_book_pages(scan_id: str) -> List[int]:
    """Get list of page numbers for a book."""
    source_dir = LIBRARY_ROOT / scan_id / "source"
    if not source_dir.exists():
        return []

    pages = []
    for img_path in sorted(source_dir.glob("page_*.png")):
        page_num = int(img_path.stem.split('_')[1])
        pages.append(page_num)

    if not pages:  # Try JPG if no PNGs
        for img_path in sorted(source_dir.glob("page_*.jpg")):
            page_num = int(img_path.stem.split('_')[1])
            pages.append(page_num)

    return sorted(pages)


def get_page_image_dimensions(scan_id: str, page_num: int) -> tuple[int, int]:
    """Get image dimensions for a page."""
    img_path = get_page_image_path(scan_id, page_num)
    if not img_path:
        return (0, 0)

    with Image.open(img_path) as img:
        return img.size


def get_stage_logs(scan_id: str, stage: str, level_filter: Optional[str] = None,
                   search: Optional[str] = None, limit: int = 50) -> List[Dict]:
    """Load and parse the latest log file for a stage.

    Args:
        scan_id: Book identifier
        stage: Stage name (ocr, corrected, labels, merged, build_structure)
        level_filter: Filter by log level (INFO, ERROR, WARNING)
        search: Search in message text
        limit: Max number of entries to return

    Returns:
        List of log entries (parsed JSON objects)
    """
    logs_dir = LIBRARY_ROOT / scan_id / stage / "logs"
    if not logs_dir.exists():
        return []

    # Find latest log file for this stage
    log_files = sorted(logs_dir.glob(f"{stage}_*.jsonl"), reverse=True)
    if not log_files:
        return []

    latest_log = log_files[0]

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

    Returns:
        Dict with aggregated stats or None if no report exists
    """
    from stats_calculator import (
        calculate_ocr_stats,
        calculate_corrected_stats,
        calculate_labels_stats
    )

    report_path = LIBRARY_ROOT / scan_id / stage / "report.csv"
    if not report_path.exists():
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
