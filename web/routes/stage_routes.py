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
from web.data.extract_toc_data import get_extract_toc_data, get_toc_page_numbers
from web.data.bbox_data import get_bbox_phases

stage_bp = Blueprint('stage', __name__)


@stage_bp.route('/stage/<scan_id>/extract-toc')
def extract_toc_view(scan_id: str):
    """
    Extract-toc stage detail view.

    Shows:
    - Source page images where TOC appears
    - Rendered TOC structure with entries
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

    # Get page numbers for images
    page_numbers = get_toc_page_numbers(storage)

    # Load bbox phase data for visualization
    bbox_phases = get_bbox_phases(storage)

    return render_template(
        'stage/extract_toc.html',
        scan_id=scan_id,
        metadata=metadata,
        toc_data=toc_data,
        page_numbers=page_numbers,
        bbox_phases=bbox_phases,
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
