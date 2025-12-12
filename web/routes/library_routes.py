"""
Library routes blueprint.

Mirrors cli/namespace_library.py operations:
- GET / - List all books with status (like `shelf library list`)
- GET /book/<scan_id>/metadata - View book metadata
"""

from flask import Blueprint, render_template, abort
from web.config import Config
from web.data.library_data import get_all_books
from web.data.ocr_pages_data import get_metadata_status
from infra.pipeline.storage.library import Library

library_bp = Blueprint('library', __name__)


@library_bp.route('/')
def library_list():
    """
    Library list view.

    Shows all books with stage status, progress, and metrics.
    Mirrors `shelf library list` command.
    """
    books = get_all_books(storage_root=Config.BOOK_STORAGE_ROOT)

    # Calculate library-wide totals
    library_total_cost = sum(book['total_cost_usd'] for book in books)
    library_total_runtime = sum(book['total_runtime_seconds'] for book in books)

    return render_template(
        'library/list.html',
        books=books,
        library_total_cost=library_total_cost,
        library_total_runtime=library_total_runtime,
        active='library',
    )


@library_bp.route('/book/<scan_id>/metadata')
def book_metadata(scan_id: str):
    """
    Book metadata detail view.

    Shows all extracted metadata for a book.
    """
    library = Library(storage_root=Config.BOOK_STORAGE_ROOT)

    if not library.get_scan_info(scan_id):
        abort(404, f"Book '{scan_id}' not found")

    storage = library.get_book_storage(scan_id)
    metadata = get_metadata_status(storage)

    if not metadata:
        abort(404, f"No metadata extracted for '{scan_id}'")

    return render_template(
        'book/metadata.html',
        scan_id=scan_id,
        metadata=metadata,
    )
