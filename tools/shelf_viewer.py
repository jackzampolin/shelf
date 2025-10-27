#!/usr/bin/env python3
"""
Shelf Viewer - Unified Flask app for debugging book processing pipeline.

This is the main Flask application that provides web-based viewers for all
pipeline stages. Data loading and statistics calculations are in separate modules.

Usage:
    python tools/shelf_viewer.py [--port 5001] [--host 127.0.0.1]
"""

import csv
import json
import os
from pathlib import Path

from flask import Flask, render_template, send_file, abort, request, redirect

# Import data loading utilities
from data_loaders import (
    LIBRARY_ROOT,
    find_all_books,
    get_page_image_path,
    get_stage_data,
    get_book_pages,
    get_page_image_dimensions,
    get_stage_logs,
    get_stage_stats,
)

# Initialize Flask app
app = Flask(__name__)


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
    print(f"✨ Open http://{args.host}:{args.port} in your browser\n")

    app.run(host=args.host, port=args.port, debug=True)
