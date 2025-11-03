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

    return render_template(
        'library/list.html',
        books=books,
        active='library',
    )
