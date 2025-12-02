"""
Test storage helper for creating isolated test workspaces.

Creates temporary test directories that symlink to library data,
allowing tests to read from production library without overwriting outputs.
"""

import shutil
from pathlib import Path
from typing import Optional
import os

from infra.pipeline.storage.book_storage import BookStorage


def get_library_root() -> Path:
    """Get the library root directory."""
    # Check environment variable first
    env_root = os.environ.get('BOOK_STORAGE_ROOT')
    if env_root:
        return Path(env_root).expanduser()

    # Default location
    return Path.home() / "Documents" / "book_scans"


def get_test_output_root() -> Path:
    """Get the test output directory."""
    return Path(__file__).parent.parent / "test_outputs"


def create_test_storage(
    book_id: str,
    clean: bool = True,
    library_root: Optional[Path] = None
) -> BookStorage:
    """
    Create isolated test storage for a book.

    This creates a temporary test workspace that:
    - Symlinks read-only data from library (source/, ocr-pages/, metadata.json, etc.)
    - Allows stages to write outputs to test workspace
    - Prevents overwriting production library data

    Args:
        book_id: Book scan ID
        clean: If True, remove existing test workspace first
        library_root: Override library location (default: ~/Documents/book_scans)

    Returns:
        BookStorage pointing to test workspace

    Example:
        >>> storage = create_test_storage("accidental-president")
        >>> stage = ExtractTocStage(storage)
        >>> stage.run()  # Writes to test_outputs/, not library
    """
    if library_root is None:
        library_root = get_library_root()

    test_root = get_test_output_root()

    library_book_dir = library_root / book_id
    test_book_dir = test_root / book_id

    # Validate library book exists
    if not library_book_dir.exists():
        raise ValueError(f"Book not found in library: {book_id} at {library_book_dir}")

    # Clean existing test workspace if requested
    if clean and test_book_dir.exists():
        shutil.rmtree(test_book_dir)

    # Create test workspace
    test_book_dir.mkdir(parents=True, exist_ok=True)

    # Symlink read-only data from library
    # These are inputs that stages read from
    readonly_items = [
        "source",           # Source images
        "ocr-pages",        # OCR outputs
        "metadata.json",    # Book metadata
        "label-structure",  # For link-toc tests
        "extract-toc",      # For link-toc tests
    ]

    for item in readonly_items:
        src = library_book_dir / item
        dst = test_book_dir / item

        # Skip if doesn't exist in library (might not be needed for all tests)
        if not src.exists():
            continue

        # Skip if already symlinked
        if dst.exists() or dst.is_symlink():
            continue

        # Create symlink
        dst.symlink_to(src)

    # Return BookStorage pointing to test workspace
    return BookStorage(book_id, storage_root=test_root)


def cleanup_test_outputs(book_id: Optional[str] = None):
    """
    Clean up test outputs.

    Args:
        book_id: If provided, clean only this book. Otherwise clean all.
    """
    test_root = get_test_output_root()

    if book_id:
        book_dir = test_root / book_id
        if book_dir.exists():
            shutil.rmtree(book_dir)
    else:
        # Clean all test outputs
        if test_root.exists():
            shutil.rmtree(test_root)


def list_test_workspaces() -> list[str]:
    """List all active test workspaces."""
    test_root = get_test_output_root()
    if not test_root.exists():
        return []

    return [d.name for d in test_root.iterdir() if d.is_dir()]
