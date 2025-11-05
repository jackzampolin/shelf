"""
Stage detail view routes.

Provides views for individual stage outputs:
- /stage/<scan_id>/<stage_name> - Stage detail view
- /image/<scan_id>/source/<page_num> - Serve source page image
"""

from flask import Blueprint, render_template, send_file, abort
from pathlib import Path

from web.config import Config
from infra.storage.library import Library
from web.data.extract_toc_data import get_extract_toc_data
from web.data.find_toc_data import get_find_toc_data, get_toc_page_numbers
from web.data.label_pages_data import get_label_pages_report, get_page_labels

stage_bp = Blueprint('stage', __name__)


@stage_bp.route('/stage/<scan_id>/find-toc')
def find_toc_view(scan_id: str):
    """
    Find-toc stage detail view.

    Shows:
    - TOC page images on the left (from find-toc result)
    - Finder analysis on the right (confidence, reasoning, structure summary)
    """
    library = Library(storage_root=Config.BOOK_STORAGE_ROOT)

    # Get book metadata
    metadata = library.get_scan_info(scan_id)
    if not metadata:
        abort(404, f"Book '{scan_id}' not found")

    storage = library.get_book_storage(scan_id)

    # Load find-toc data from disk
    finder_data = get_find_toc_data(storage)

    if not finder_data:
        abort(404, f"Find-toc stage not run for '{scan_id}'")

    # Get page numbers for images
    page_numbers = get_toc_page_numbers(storage)

    return render_template(
        'stage/find_toc.html',
        scan_id=scan_id,
        metadata=metadata,
        finder_data=finder_data,
        page_numbers=page_numbers,
    )


@stage_bp.route('/stage/<scan_id>/extract-toc')
def extract_toc_view(scan_id: str):
    """
    Extract-toc stage detail view.

    Shows:
    - TOC page images on the left (from find-toc)
    - Parsed TOC structure on the right (from extract-toc)
    """
    library = Library(storage_root=Config.BOOK_STORAGE_ROOT)

    # Get book metadata (returns None if book doesn't exist)
    metadata = library.get_scan_info(scan_id)
    if not metadata:
        abort(404, f"Book '{scan_id}' not found")

    storage = library.get_book_storage(scan_id)

    # Load extract-toc data from disk
    toc_data = get_extract_toc_data(storage)

    if not toc_data:
        abort(404, f"Extract-toc stage not run for '{scan_id}'")

    # Get page numbers for images (from find-toc stage)
    page_numbers = get_toc_page_numbers(storage)

    return render_template(
        'stage/extract_toc.html',
        scan_id=scan_id,
        metadata=metadata,
        toc_data=toc_data,
        page_numbers=page_numbers,
    )


@stage_bp.route('/stage/<scan_id>/label-pages')
def label_pages_view(scan_id: str):
    """
    Label-pages stage detail view.

    Shows:
    - Report table with all page labels
    - Links to individual page viewers
    """
    library = Library(storage_root=Config.BOOK_STORAGE_ROOT)

    # Get book metadata
    metadata = library.get_scan_info(scan_id)
    if not metadata:
        abort(404, f"Book '{scan_id}' not found")

    storage = library.get_book_storage(scan_id)

    # Load label-pages report from disk
    report = get_label_pages_report(storage)

    if not report:
        abort(404, f"Label-pages stage not run for '{scan_id}'")

    return render_template(
        'stage/label_pages.html',
        scan_id=scan_id,
        metadata=metadata,
        report=report,
    )


@stage_bp.route('/stage/<scan_id>/label-pages/page/<int:page_num>')
def label_pages_page_view(scan_id: str, page_num: int):
    """
    Individual page view for label-pages stage.

    Shows:
    - Page image on left
    - Page labels on right in human-readable format
    """
    library = Library(storage_root=Config.BOOK_STORAGE_ROOT)

    # Get book metadata
    metadata = library.get_scan_info(scan_id)
    if not metadata:
        abort(404, f"Book '{scan_id}' not found")

    storage = library.get_book_storage(scan_id)

    # Get labels for this page
    labels = get_page_labels(storage, page_num)

    if not labels:
        abort(404, f"Page {page_num} not found in label-pages report")

    return render_template(
        'stage/label_pages_page.html',
        scan_id=scan_id,
        metadata=metadata,
        page_num=page_num,
        labels=labels,
    )


@stage_bp.route('/image/<scan_id>/source/<int:page_num>')
def serve_source_image(scan_id: str, page_num: int):
    """
    Serve source page image.

    Returns PNG image from source/ directory.
    """
    library = Library(storage_root=Config.BOOK_STORAGE_ROOT)

    # Check book exists
    if not library.get_scan_info(scan_id):
        abort(404, f"Book '{scan_id}' not found")

    storage = library.get_book_storage(scan_id)
    source_dir = storage.book_dir / "source"

    # Format page number: page_0001.png
    image_filename = f"page_{page_num:04d}.png"
    image_path = source_dir / image_filename

    if not image_path.exists():
        abort(404, f"Page image not found: {image_filename}")

    return send_file(str(image_path), mimetype='image/png')
