"""
Library routes blueprint.

Mirrors cli/namespace_library.py operations:
- GET / - List all books with status (like `shelf library list`)
"""

from flask import Blueprint, render_template
from web.config import Config
from web.data.library_data import get_all_books

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
