#!/usr/bin/env python3
"""
Shelf Viewer - Unified Flask app for debugging book processing pipeline.

Tools:
- ToC Viewer: View parsed table of contents with page images
- Correction Viewer: Compare OCR output with corrections
- Label Viewer: View page labels with visual overlays
- Stats Viewer: View book-level label statistics

Usage:
    python tools/shelf_viewer_new.py [--port 5000] [--host 127.0.0.1]
"""

import csv
import json
import os
from pathlib import Path
from typing import Optional, List, Dict, Any

from flask import Flask, render_template, send_file, abort
from PIL import Image

# Initialize Flask app
app = Flask(__name__)

# Get library root from env or default
LIBRARY_ROOT = Path(os.getenv("BOOK_STORAGE_ROOT", "~/Documents/book_scans")).expanduser()


# ============================================================================
# Shared Utilities
# ============================================================================

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
            return _calculate_ocr_stats(rows, total_pages)
        elif stage == "corrected":
            return _calculate_corrected_stats(rows, total_pages)
        elif stage == "labels":
            return _calculate_labels_stats(rows, total_pages)
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
                "rows": rows[:10],
            }
    except Exception:
        return None


def _calculate_ocr_stats(rows: List[Dict], total_pages: int) -> Dict[str, Any]:
    """Calculate detailed OCR-specific statistics."""
    confidences = []
    blocks = []
    low_quality_pages = []

    for row in rows:
        page_num = int(row['page_num'])

        # Confidence
        if 'confidence_mean' in row and row['confidence_mean']:
            try:
                conf = float(row['confidence_mean'])
                confidences.append(conf)

                # Flag low quality pages (< 0.8)
                if conf < 0.8:
                    low_quality_pages.append((page_num, conf))
            except ValueError:
                pass

        # Blocks
        if 'blocks_detected' in row and row['blocks_detected']:
            try:
                blocks.append(int(row['blocks_detected']))
            except ValueError:
                pass

    # Sort low quality pages by confidence (worst first)
    low_quality_pages.sort(key=lambda x: x[1])

    # Calculate confidence histogram bins
    histogram = {
        "0.0-0.5": 0,  # Unreadable
        "0.5-0.7": 0,  # Marginal
        "0.7-0.8": 0,  # Acceptable
        "0.8-0.9": 0,  # Good
        "0.9-1.0": 0,  # Excellent
    }

    for conf in confidences:
        if conf < 0.5:
            histogram["0.0-0.5"] += 1
        elif conf < 0.7:
            histogram["0.5-0.7"] += 1
        elif conf < 0.8:
            histogram["0.7-0.8"] += 1
        elif conf < 0.9:
            histogram["0.8-0.9"] += 1
        else:
            histogram["0.9-1.0"] += 1

    return {
        "total_pages": total_pages,
        "avg_confidence": sum(confidences) / len(confidences) if confidences else None,
        "min_confidence": min(confidences) if confidences else None,
        "max_confidence": max(confidences) if confidences else None,
        "avg_blocks": sum(blocks) / len(blocks) if blocks else None,
        "min_blocks": min(blocks) if blocks else None,
        "max_blocks": max(blocks) if blocks else None,
        "low_quality_count": len(low_quality_pages),
        "low_quality_pages": low_quality_pages[:20],  # Top 20 worst
        "confidence_histogram": histogram,
    }


def _calculate_corrected_stats(rows: List[Dict], total_pages: int) -> Dict[str, Any]:
    """Calculate detailed correction-specific statistics.

    Key metrics:
    - text_similarity_ratio: Most important (0.95-1.0 green, 0.85-0.95 yellow, <0.85 red)
    - avg_confidence: Model confidence in corrections
    - total_corrections: Number of paragraphs corrected
    - characters_changed: Edit distance
    """
    similarities = []
    confidences = []
    corrections = []
    chars_changed = []
    problem_pages = []

    for row in rows:
        page_num = int(row['page_num'])

        # Text similarity (most important metric)
        if 'text_similarity_ratio' in row and row['text_similarity_ratio']:
            try:
                sim = float(row['text_similarity_ratio'])
                similarities.append(sim)

                # Flag problem pages (< 0.90 similarity or low confidence)
                conf = float(row.get('avg_confidence', 0))
                if sim < 0.90 or conf < 0.85:
                    problem_pages.append({
                        'page_num': page_num,
                        'similarity': sim,
                        'confidence': conf,
                        'corrections': int(row.get('total_corrections', 0))
                    })
            except (ValueError, TypeError):
                pass

        # Confidence
        if 'avg_confidence' in row and row['avg_confidence']:
            try:
                confidences.append(float(row['avg_confidence']))
            except ValueError:
                pass

        # Correction count
        if 'total_corrections' in row and row['total_corrections']:
            try:
                corrections.append(int(row['total_corrections']))
            except ValueError:
                pass

        # Characters changed
        if 'characters_changed' in row and row['characters_changed']:
            try:
                chars_changed.append(int(row['characters_changed']))
            except ValueError:
                pass

    # Sort problem pages by similarity (worst first)
    problem_pages.sort(key=lambda x: x['similarity'])

    # Calculate similarity histogram bins
    similarity_histogram = {
        "0.00-0.85": 0,  # Red flag (over-correction)
        "0.85-0.90": 0,  # Concerning
        "0.90-0.95": 0,  # Normal corrections
        "0.95-0.98": 0,  # Minor fixes
        "0.98-1.00": 0,  # Very minor fixes
    }

    for sim in similarities:
        if sim < 0.85:
            similarity_histogram["0.00-0.85"] += 1
        elif sim < 0.90:
            similarity_histogram["0.85-0.90"] += 1
        elif sim < 0.95:
            similarity_histogram["0.90-0.95"] += 1
        elif sim < 0.98:
            similarity_histogram["0.95-0.98"] += 1
        else:
            similarity_histogram["0.98-1.00"] += 1

    # Calculate confidence histogram bins
    confidence_histogram = {
        "0.0-0.5": 0,
        "0.5-0.7": 0,
        "0.7-0.85": 0,
        "0.85-0.95": 0,
        "0.95-1.0": 0,
    }

    for conf in confidences:
        if conf < 0.5:
            confidence_histogram["0.0-0.5"] += 1
        elif conf < 0.7:
            confidence_histogram["0.5-0.7"] += 1
        elif conf < 0.85:
            confidence_histogram["0.7-0.85"] += 1
        elif conf < 0.95:
            confidence_histogram["0.85-0.95"] += 1
        else:
            confidence_histogram["0.95-1.0"] += 1

    return {
        "total_pages": total_pages,
        "avg_similarity": sum(similarities) / len(similarities) if similarities else None,
        "min_similarity": min(similarities) if similarities else None,
        "max_similarity": max(similarities) if similarities else None,
        "avg_confidence": sum(confidences) / len(confidences) if confidences else None,
        "min_confidence": min(confidences) if confidences else None,
        "max_confidence": max(confidences) if confidences else None,
        "total_corrections": sum(corrections) if corrections else 0,
        "avg_corrections": sum(corrections) / len(corrections) if corrections else None,
        "avg_chars_changed": sum(chars_changed) / len(chars_changed) if chars_changed else None,
        "problem_pages": problem_pages[:20],  # Top 20 worst
        "similarity_histogram": similarity_histogram,
        "confidence_histogram": confidence_histogram,
    }


def _calculate_labels_stats(rows: List[Dict], total_pages: int) -> Dict[str, Any]:
    """Calculate detailed label-specific statistics.

    Key metrics:
    - avg_classification_confidence: Block classification quality
    - page_number_extracted: Printed page numbers found
    - page_region_classified: Regions identified
    - has_chapter_heading: Chapter boundary markers
    """
    confidences = []
    page_numbers_extracted = 0
    regions_classified = 0
    chapter_headings = []
    problem_pages = []
    region_breakdown = {"front_matter": 0, "body": 0, "back_matter": 0, "toc_area": 0, "unknown": 0}

    for row in rows:
        page_num = int(row['page_num'])

        # Confidence
        if 'avg_classification_confidence' in row and row['avg_classification_confidence']:
            try:
                conf = float(row['avg_classification_confidence'])
                confidences.append(conf)

                # Flag problem pages (< 0.80 confidence or missing classification)
                if conf < 0.80:
                    problem_pages.append({
                        'page_num': page_num,
                        'confidence': conf,
                        'region': row.get('page_region', 'unknown'),
                        'blocks': int(row.get('total_blocks_classified', 0))
                    })
            except (ValueError, TypeError):
                pass

        # Page number extraction
        if row.get('page_number_extracted', '').lower() == 'true':
            page_numbers_extracted += 1

        # Region classification
        region = row.get('page_region', 'unknown')
        if region and region != 'null':
            regions_classified += 1
            region_breakdown[region] = region_breakdown.get(region, 0) + 1
        else:
            region_breakdown['unknown'] += 1

        # Chapter headings
        if row.get('has_chapter_heading', '').lower() == 'true':
            chapter_headings.append({
                'page_num': page_num,
                'printed_page': row.get('printed_page_number', '-'),
                'text': row.get('chapter_heading_text', '(No text)')
            })

    # Sort problem pages by confidence (worst first)
    problem_pages.sort(key=lambda x: x['confidence'])

    # Calculate confidence histogram bins
    confidence_histogram = {
        "0.00-0.80": 0,  # Red flag
        "0.80-0.85": 0,  # Concerning
        "0.85-0.90": 0,  # Acceptable
        "0.90-0.95": 0,  # Good
        "0.95-1.00": 0,  # Excellent
    }

    for conf in confidences:
        if conf < 0.80:
            confidence_histogram["0.00-0.80"] += 1
        elif conf < 0.85:
            confidence_histogram["0.80-0.85"] += 1
        elif conf < 0.90:
            confidence_histogram["0.85-0.90"] += 1
        elif conf < 0.95:
            confidence_histogram["0.90-0.95"] += 1
        else:
            confidence_histogram["0.95-1.00"] += 1

    return {
        "total_pages": total_pages,
        "avg_confidence": sum(confidences) / len(confidences) if confidences else None,
        "min_confidence": min(confidences) if confidences else None,
        "max_confidence": max(confidences) if confidences else None,
        "page_numbers_extracted": page_numbers_extracted,
        "page_numbers_percentage": (page_numbers_extracted / total_pages * 100) if total_pages > 0 else 0,
        "regions_classified": regions_classified,
        "regions_percentage": (regions_classified / total_pages * 100) if total_pages > 0 else 0,
        "chapter_headings_count": len(chapter_headings),
        "chapter_headings": chapter_headings[:20],  # Top 20
        "region_breakdown": region_breakdown,
        "problem_pages": problem_pages[:20],  # Top 20 worst
        "confidence_histogram": confidence_histogram,
    }


# ============================================================================
# Routes
# ============================================================================

@app.route("/")
def home():
    """Home page with library status table."""
    books = find_all_books()

    return render_template('home.html', active='home', books=books)


@app.route("/toc")
def toc_list():
    """List books with ToC data."""
    books = []
    for book_dir in sorted(LIBRARY_ROOT.iterdir()):
        if not book_dir.is_dir() or book_dir.name.startswith('.'):
            continue
        toc_path = book_dir / "build_structure" / "toc.json"
        if toc_path.exists():
            with open(toc_path) as f:
                toc_data = json.load(f)
            # Skip if no ToC found
            if "note" in toc_data and "No ToC found" in toc_data["note"]:
                continue
            books.append({
                "scan_id": book_dir.name,
                "entry_count": len(toc_data.get("entries", [])),
                "page_range": toc_data.get("toc_page_range", {}),
            })

    return render_template('toc/list.html', active='toc', books=books)


@app.route("/toc/<scan_id>")
def toc_view(scan_id: str):
    """View ToC for a specific book."""
    toc_path = LIBRARY_ROOT / scan_id / "build_structure" / "toc.json"
    if not toc_path.exists():
        abort(404, f"No ToC data found for {scan_id}")

    with open(toc_path) as f:
        toc_data = json.load(f)

    page_range = toc_data.get("toc_page_range", {})
    start_page = page_range.get("start_page", 1)
    end_page = page_range.get("end_page", 1)
    page_numbers = list(range(start_page, end_page + 1))

    return render_template(
        'toc/viewer.html',
        active='toc',
        scan_id=scan_id,
        toc_data=toc_data,
        page_numbers=page_numbers,
    )


@app.route("/corrections")
def correction_list():
    """List books with correction data."""
    books = []
    for book_dir in sorted(LIBRARY_ROOT.iterdir()):
        if not book_dir.is_dir() or book_dir.name.startswith('.'):
            continue
        corrections_dir = book_dir / "corrected"
        if corrections_dir.exists():
            page_count = len(list(corrections_dir.glob("page_*.json")))
            if page_count > 0:
                books.append({
                    "scan_id": book_dir.name,
                    "page_count": page_count,
                })

    return render_template('corrections/list.html', active='corrections', books=books)


@app.route("/corrections/<scan_id>")
def correction_redirect(scan_id: str):
    """Redirect to first page of corrections."""
    from flask import redirect
    all_pages = get_book_pages(scan_id)
    if not all_pages:
        abort(404, f"No pages found for {scan_id}")
    return redirect(f"/corrections/{scan_id}/{all_pages[0]}")


@app.route("/corrections/<scan_id>/<int:page_num>")
def correction_view(scan_id: str, page_num: int):
    """View corrections for a specific book page."""
    all_pages = get_book_pages(scan_id)
    if not all_pages:
        abort(404, f"No pages found for {scan_id}")

    if page_num not in all_pages:
        abort(404, f"Page {page_num} not found")

    ocr_data = get_stage_data(scan_id, "ocr", page_num)
    correction_data = get_stage_data(scan_id, "corrected", page_num)

    return render_template(
        'corrections/viewer.html',
        active='corrections',
        scan_id=scan_id,
        current_page=page_num,
        all_pages=all_pages,
        ocr_data=ocr_data,
        correction_data=correction_data,
    )


@app.route("/api/corrections/<scan_id>/page")
def correction_page_api(scan_id: str):
    """HTMX API endpoint for page content updates."""
    from flask import request
    page_num = int(request.args.get('page', 1))

    all_pages = get_book_pages(scan_id)
    if page_num not in all_pages:
        abort(404, f"Page {page_num} not found")

    ocr_data = get_stage_data(scan_id, "ocr", page_num)
    correction_data = get_stage_data(scan_id, "corrected", page_num)

    return render_template(
        'corrections/_page_content.html',
        scan_id=scan_id,
        current_page=page_num,
        ocr_data=ocr_data,
        correction_data=correction_data,
    )


@app.route("/labels")
def label_list():
    """List books with label data."""
    books = []
    for book_dir in sorted(LIBRARY_ROOT.iterdir()):
        if not book_dir.is_dir() or book_dir.name.startswith('.'):
            continue
        labels_dir = book_dir / "labels"
        if labels_dir.exists():
            page_count = len(list(labels_dir.glob("page_*.json")))
            if page_count > 0:
                books.append({
                    "scan_id": book_dir.name,
                    "page_count": page_count,
                })

    return render_template('labels/list.html', active='labels', books=books)


@app.route("/labels/<scan_id>")
def label_redirect(scan_id: str):
    """Redirect to first page of labels."""
    from flask import redirect
    all_pages = get_book_pages(scan_id)
    if not all_pages:
        abort(404, f"No pages found for {scan_id}")
    return redirect(f"/labels/{scan_id}/{all_pages[0]}")


@app.route("/labels/<scan_id>/<int:page_num>")
def label_view(scan_id: str, page_num: int):
    """View labels for a specific book page."""
    all_pages = get_book_pages(scan_id)
    if not all_pages:
        abort(404, f"No pages found for {scan_id}")

    if page_num not in all_pages:
        abort(404, f"Page {page_num} not found")

    label_data = get_stage_data(scan_id, "labels", page_num)
    ocr_data = get_stage_data(scan_id, "ocr", page_num)

    # Get image dimensions for canvas scaling
    image_width, image_height = get_page_image_dimensions(scan_id, page_num)

    return render_template(
        'labels/viewer.html',
        active='labels',
        scan_id=scan_id,
        current_page=page_num,
        all_pages=all_pages,
        label_data=label_data,
        ocr_data=ocr_data,
        image_width=image_width,
        image_height=image_height,
    )


@app.route("/stats")
def stats_list():
    """List books with stats."""
    books = []
    for book_dir in sorted(LIBRARY_ROOT.iterdir()):
        if not book_dir.is_dir() or book_dir.name.startswith('.'):
            continue
        report_path = book_dir / "labels" / "report.csv"
        if report_path.exists():
            with open(report_path) as f:
                page_count = sum(1 for _ in csv.DictReader(f))
            books.append({
                "scan_id": book_dir.name,
                "page_count": page_count,
            })

    return render_template('stats/list.html', active='stats', books=books)


@app.route("/stats/<scan_id>")
def stats_view(scan_id: str):
    """View stats for a specific book."""
    report_path = LIBRARY_ROOT / scan_id / "labels" / "report.csv"
    if not report_path.exists():
        abort(404, f"No stats found for {scan_id}")

    # Parse report.csv
    with open(report_path) as f:
        rows = list(csv.DictReader(f))

    # Calculate statistics
    total_pages = len(rows)
    total_blocks = sum(int(row.get('block_count', 0)) for row in rows)
    chapter_headings = sum(1 for row in rows if row.get('has_chapter_heading', '').lower() == 'true')

    # Calculate average confidence
    confidences = [float(row.get('avg_confidence', 0)) for row in rows if row.get('avg_confidence')]
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

    # Region breakdown
    region_breakdown = {}
    for row in rows:
        region = row.get('page_region', 'unknown')
        region_breakdown[region] = region_breakdown.get(region, 0) + 1

    # Block type breakdown (aggregate across all pages)
    block_type_breakdown = {}
    for row in rows:
        # Parse block_types field (comma-separated)
        block_types = row.get('block_types', '').split(',')
        for bt in block_types:
            bt = bt.strip()
            if bt:
                block_type_breakdown[bt] = block_type_breakdown.get(bt, 0) + 1

    # Sample pages (first 50)
    sample_pages = []
    for row in rows[:50]:
        sample_pages.append({
            "page_num": int(row['page_num']),
            "printed_page_number": row.get('printed_page_number'),
            "page_region": row.get('page_region', 'unknown'),
            "block_count": int(row.get('block_count', 0)),
            "has_chapter_heading": row.get('has_chapter_heading', '').lower() == 'true',
            "avg_confidence": float(row.get('avg_confidence', 0)),
        })

    stats = {
        "total_pages": total_pages,
        "total_blocks": total_blocks,
        "avg_confidence": avg_confidence,
        "chapter_headings": chapter_headings,
        "region_breakdown": region_breakdown,
        "block_type_breakdown": block_type_breakdown,
        "sample_pages": sample_pages,
    }

    return render_template('stats/viewer.html', active='stats', scan_id=scan_id, stats=stats)


@app.route("/stage/<scan_id>/<stage_name>")
def stage_view(scan_id: str, stage_name: str):
    """Stage overview with stats and logs."""
    from flask import request

    # Validate stage name
    valid_stages = ["ocr", "corrected", "labels", "merged", "build_structure"]
    if stage_name not in valid_stages:
        abort(404, f"Invalid stage: {stage_name}")

    # Special handling for build_structure (uses toc.json)
    if stage_name == "build_structure":
        toc_path = LIBRARY_ROOT / scan_id / "build_structure" / "toc.json"
        has_toc = toc_path.exists()
        toc_data = None

        if has_toc:
            with open(toc_path) as f:
                toc_data = json.load(f)
            # Check if ToC was actually found
            if "note" in toc_data and "No ToC found" in toc_data["note"]:
                has_toc = False
                toc_data = None

        # Get latest logs
        level_filter = request.args.get('level')
        search = request.args.get('search')
        logs = get_stage_logs(scan_id, stage_name, level_filter=level_filter, search=search)

        return render_template(
            'stage/build_structure.html',
            active='stage',
            scan_id=scan_id,
            stage_name=stage_name,
            has_toc=has_toc,
            toc_data=toc_data,
            logs=logs,
        )

    # Standard handling for other stages
    # Get stats from report.csv
    stats = get_stage_stats(scan_id, stage_name)

    # Get latest logs
    level_filter = request.args.get('level')
    search = request.args.get('search')
    logs = get_stage_logs(scan_id, stage_name, level_filter=level_filter, search=search)

    return render_template(
        f'stage/{stage_name}.html',
        active='stage',
        scan_id=scan_id,
        stage_name=stage_name,
        stats=stats,
        logs=logs,
    )


@app.route("/stage/<scan_id>/<stage_name>/viewer")
def stage_viewer(scan_id: str, stage_name: str):
    """Full-screen page-by-page viewer for a stage."""
    from flask import request

    # Validate stage name
    valid_stages = ["ocr", "corrected", "labels", "merged", "build_structure"]
    if stage_name not in valid_stages:
        abort(404, f"Invalid stage: {stage_name}")

    # Special handling for build_structure (ToC viewer)
    if stage_name == "build_structure":
        toc_path = LIBRARY_ROOT / scan_id / "build_structure" / "toc.json"
        if not toc_path.exists():
            abort(404, f"No ToC data found for {scan_id}")

        with open(toc_path) as f:
            toc_data = json.load(f)

        page_range = toc_data.get("toc_page_range", {})
        start_page = page_range.get("start_page", 1)
        end_page = page_range.get("end_page", 1)
        page_numbers = list(range(start_page, end_page + 1))

        return render_template(
            'stage/build_structure_viewer.html',
            active='stage',
            scan_id=scan_id,
            toc_data=toc_data,
            page_numbers=page_numbers,
        )

    # Standard handling for other stages
    # Get page list
    all_pages = get_book_pages(scan_id)
    if not all_pages:
        abort(404, f"No pages found for {scan_id}")

    # Default to first page
    current_page = int(request.args.get('page', all_pages[0]))
    if current_page not in all_pages:
        current_page = all_pages[0]

    # Get stage data for current page
    stage_data = get_stage_data(scan_id, stage_name, current_page)
    ocr_data = get_stage_data(scan_id, "ocr", current_page)  # Always need OCR for images

    # Get image dimensions for canvas scaling (if needed)
    image_width, image_height = get_page_image_dimensions(scan_id, current_page)

    return render_template(
        f'stage/{stage_name}_viewer.html',
        active='stage',
        scan_id=scan_id,
        stage_name=stage_name,
        current_page=current_page,
        all_pages=all_pages,
        stage_data=stage_data,
        ocr_data=ocr_data,
        image_width=image_width,
        image_height=image_height,
    )


@app.route("/image/<scan_id>/<int:page_num>")
def serve_image(scan_id: str, page_num: int):
    """Serve page image."""
    img_path = get_page_image_path(scan_id, page_num)
    if not img_path:
        abort(404, f"Image not found for page {page_num}")
    return send_file(img_path)


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Shelf Viewer - Unified debugging interface")
    parser.add_argument("--port", type=int, default=5001, help="Port to run on (default: 5001)")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to (default: 127.0.0.1)")
    args = parser.parse_args()

    print(f"\n🚀 Shelf Viewer starting on http://{args.host}:{args.port}")
    print(f"📁 Library: {LIBRARY_ROOT}\n")
    print(f"Available tools:")
    print(f"  📖 ToC Viewer      - http://{args.host}:{args.port}/toc")
    print(f"  ✏️  Corrections     - http://{args.host}:{args.port}/corrections")
    print(f"  🏷️  Labels          - http://{args.host}:{args.port}/labels")
    print(f"  📊 Stats           - http://{args.host}:{args.port}/stats")
    print(f"\n✨ Open http://{args.host}:{args.port} in your browser\n")

    app.run(host=args.host, port=args.port, debug=True)
