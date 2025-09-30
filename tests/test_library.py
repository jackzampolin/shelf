"""
Library catalog tests.

Tests library management operations (add, update, query, sync).
No mocks - tests real file operations.
"""

import pytest
import json
from pathlib import Path
from tools.library import LibraryIndex


@pytest.fixture
def empty_library(tmp_path):
    """Create an empty library for testing."""
    library_root = tmp_path / "book_scans"
    library_root.mkdir()
    return LibraryIndex(storage_root=library_root)


@pytest.fixture
def library_with_books(empty_library):
    """Create a library with test books."""
    # Add first book
    empty_library.add_book(
        title="Test Book One",
        author="Author One",
        scan_id="test-one",
        isbn="978-1234567890",
        year=2020,
        tags=["history", "test"]
    )

    # Add second book
    empty_library.add_book(
        title="Test Book Two",
        author="Author Two",
        scan_id="test-two",
        isbn="978-0987654321",
        year=2021,
        tags=["biography"]
    )

    return empty_library


def test_library_initialization(empty_library):
    """Test that library initializes with correct structure."""
    assert empty_library.library_file.exists(), "library.json should exist"
    assert empty_library.data['version'] == "1.0", "Should have version"
    assert 'books' in empty_library.data, "Should have books dict"
    assert 'stats' in empty_library.data, "Should have stats"
    assert empty_library.data['stats']['total_books'] == 0, "Should start with 0 books"


def test_add_book(empty_library):
    """Test adding a book to the library."""
    book_slug = empty_library.add_book(
        title="The Accidental President",
        author="A. J. Baime",
        scan_id="modest-lovelace",
        isbn="978-0544617346",
        year=2017,
        publisher="Houghton Mifflin",
        tags=["history", "biography", "wwii"],
        notes="First complete book"
    )

    assert book_slug == "the-accidental-president", "Should generate correct slug"
    assert book_slug in empty_library.data['books'], "Book should be in catalog"

    book = empty_library.data['books'][book_slug]
    assert book['title'] == "The Accidental President"
    assert book['author'] == "A. J. Baime"
    assert book['isbn'] == "978-0544617346"
    assert book['year'] == 2017
    assert "history" in book['tags']
    assert len(book['scans']) == 1, "Should have one scan"

    scan = book['scans'][0]
    assert scan['scan_id'] == "modest-lovelace"
    assert scan['status'] == "registered"
    assert scan['pages'] == 0  # Not processed yet
    assert scan['cost_usd'] == 0.0


def test_list_all_books_empty(empty_library):
    """Test listing books when library is empty."""
    books = empty_library.list_all_books()
    assert books == [], "Empty library should return empty list"


def test_list_all_books(library_with_books):
    """Test listing all books in library."""
    books = library_with_books.list_all_books()

    assert len(books) == 2, "Should have 2 books"

    titles = [b['title'] for b in books]
    assert "Test Book One" in titles
    assert "Test Book Two" in titles


def test_get_scan_info_found(library_with_books):
    """Test getting scan info for existing scan."""
    scan_info = library_with_books.get_scan_info("test-one")

    assert scan_info is not None, "Should find scan"
    assert scan_info['title'] == "Test Book One"
    assert scan_info['author'] == "Author One"
    assert scan_info['scan']['scan_id'] == "test-one"


def test_get_scan_info_not_found(library_with_books):
    """Test getting scan info for non-existent scan."""
    scan_info = library_with_books.get_scan_info("nonexistent")
    assert scan_info is None, "Should return None for non-existent scan"


def test_update_scan_metadata(library_with_books):
    """Test updating scan metadata."""
    library_with_books.update_scan_metadata("test-one", {
        'status': 'processing',
        'pages': 100,
        'cost_usd': 5.50
    })

    scan_info = library_with_books.get_scan_info("test-one")
    assert scan_info['scan']['status'] == 'processing'
    assert scan_info['scan']['pages'] == 100
    assert scan_info['scan']['cost_usd'] == 5.50


def test_get_stats(library_with_books):
    """Test getting library statistics."""
    # Update one book with pages and cost
    library_with_books.update_scan_metadata("test-one", {
        'pages': 100,
        'cost_usd': 5.00
    })

    library_with_books.update_scan_metadata("test-two", {
        'pages': 200,
        'cost_usd': 10.00
    })

    stats = library_with_books.get_stats()

    assert stats['total_books'] == 2
    assert stats['total_scans'] == 2
    assert stats['total_pages'] == 300
    assert stats['total_cost_usd'] == 15.00


def test_add_multiple_scans_same_book(empty_library):
    """Test adding multiple scans of the same book."""
    # Add first scan
    empty_library.add_book(
        title="The Accidental President",
        author="A. J. Baime",
        scan_id="scan-one",
        notes="First scan"
    )

    # Add second scan of same book
    empty_library.add_book(
        title="The Accidental President",
        author="A. J. Baime",
        scan_id="scan-two",
        notes="Second scan, better quality"
    )

    book_slug = "the-accidental-president"
    book = empty_library.data['books'][book_slug]

    assert len(book['scans']) == 2, "Should have 2 scans"

    scan_ids = [s['scan_id'] for s in book['scans']]
    assert "scan-one" in scan_ids
    assert "scan-two" in scan_ids


def test_sync_scan_from_metadata(empty_library, tmp_path):
    """Test syncing scan data from metadata.json to library.json."""
    from utils import update_book_metadata

    # Setup: Create a scan directory with metadata
    scan_id = "test-sync"
    scan_dir = empty_library.storage_root / scan_id
    scan_dir.mkdir()

    # Add to library first
    empty_library.add_book(
        title="Test Sync",
        author="Test Author",
        scan_id=scan_id
    )

    # Create metadata with processing history
    metadata_file = scan_dir / "metadata.json"
    metadata = {
        "title": "Test Sync",
        "author": "Test Author",
        "total_pages": 10,
        "processing_history": []
    }

    with open(metadata_file, 'w') as f:
        json.dump(metadata, f)

    # Add processing records with costs
    update_book_metadata(scan_dir, 'ocr', {
        'model': 'tesseract',
        'pages_processed': 10,
        'cost_usd': 0.0
    })

    update_book_metadata(scan_dir, 'correct', {
        'model': 'openai/gpt-4o-mini',
        'pages_processed': 10,
        'cost_usd': 2.50
    })

    update_book_metadata(scan_dir, 'structure', {
        'model': 'anthropic/claude-sonnet-4.5',
        'chapters_detected': 3,
        'chunks_created': 5,
        'cost_usd': 0.50
    })

    # Create structured metadata (for page count)
    structured_dir = scan_dir / "structured"
    structured_dir.mkdir()
    structured_meta = {
        "book_info": {"total_pages": 10}
    }
    with open(structured_dir / "metadata.json", 'w') as f:
        json.dump(structured_meta, f)

    # Sync to library
    empty_library.sync_scan_from_metadata(scan_id)

    # Verify library was updated
    scan_info = empty_library.get_scan_info(scan_id)

    assert scan_info['scan']['cost_usd'] == 3.00, "Cost should be synced (2.50 + 0.50)"
    assert scan_info['scan']['pages'] == 10, "Pages should be synced"
    assert 'models' in scan_info['scan'], "Models should be synced"
    assert scan_info['scan']['models']['ocr'] == 'tesseract'
    assert scan_info['scan']['models']['correct'] == 'openai/gpt-4o-mini'
    assert scan_info['scan']['models']['structure'] == 'anthropic/claude-sonnet-4.5'
    assert scan_info['scan']['status'] == 'complete', "Status should be complete"


def test_library_persists_to_disk(empty_library):
    """Test that library changes persist to disk."""
    # Add a book
    empty_library.add_book(
        title="Persistence Test",
        author="Test",
        scan_id="persist-test"
    )

    # Create new library instance (reload from disk)
    reloaded = LibraryIndex(storage_root=empty_library.storage_root)

    # Should have the book we added
    books = reloaded.list_all_books()
    assert len(books) == 1
    assert books[0]['title'] == "Persistence Test"


def test_get_book_scans(library_with_books):
    """Test getting all scans for a specific book."""
    scans = library_with_books.get_book_scans("test-book-one")

    assert len(scans) == 1
    assert scans[0]['scan_id'] == "test-one"


@pytest.mark.filesystem
def test_library_handles_missing_directory(tmp_path):
    """Test that library creates directory if it doesn't exist."""
    library_root = tmp_path / "nonexistent" / "book_scans"

    # Should create the directory
    library = LibraryIndex(storage_root=library_root)

    assert library_root.exists(), "Should create library directory"
    assert library.library_file.exists(), "Should create library.json"
