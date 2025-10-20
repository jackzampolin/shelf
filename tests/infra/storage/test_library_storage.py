"""Tests for infra/storage/library_storage.py"""

import json
from pathlib import Path
from infra.storage.library_storage import LibraryStorage


def test_library_creation(tmp_path):
    """Test that library creates library.json with proper structure."""
    library = LibraryStorage(storage_root=tmp_path)

    library_file = tmp_path / "library.json"
    assert library_file.exists()

    with open(library_file) as f:
        data = json.load(f)
        assert data["version"] == "1.0"
        assert "books" in data
        assert "stats" in data


def test_add_book(tmp_path):
    """Test adding a book to the library."""
    library = LibraryStorage(storage_root=tmp_path)

    book_slug = library.add_book(
        title="The Accidental President",
        author="Baime",
        scan_id="modest-lovelace",
        year=2017
    )

    assert book_slug == "the-accidental-president"
    assert "the-accidental-president" in library.data["books"]

    book = library.data["books"]["the-accidental-president"]
    assert book["title"] == "The Accidental President"
    assert book["author"] == "Baime"
    assert book["year"] == 2017
    assert len(book["scans"]) == 1
    assert book["scans"][0]["scan_id"] == "modest-lovelace"


def test_get_scan_info(tmp_path):
    """Test retrieving scan information."""
    library = LibraryStorage(storage_root=tmp_path)

    library.add_book(
        title="Theodore Roosevelt: An Autobiography",
        author="Roosevelt",
        scan_id="brave-curie"
    )

    info = library.get_scan_info("brave-curie")
    assert info is not None
    assert info["title"] == "Theodore Roosevelt: An Autobiography"
    assert info["author"] == "Roosevelt"
    assert info["scan"]["scan_id"] == "brave-curie"


def test_update_scan_metadata(tmp_path):
    """Test updating scan metadata."""
    library = LibraryStorage(storage_root=tmp_path)

    library.add_book(
        title="Test Book",
        author="Test Author",
        scan_id="test-scan"
    )

    library.update_scan_metadata("test-scan", {
        "status": "corrected",
        "pages": 447,
        "cost_usd": 10.25
    })

    info = library.get_scan_info("test-scan")
    assert info["scan"]["status"] == "corrected"
    assert info["scan"]["pages"] == 447
    assert info["scan"]["cost_usd"] == 10.25


def test_list_all_scans(tmp_path):
    """Test listing all scans."""
    library = LibraryStorage(storage_root=tmp_path)

    library.add_book("Book One", "Author A", "scan-1")
    library.add_book("Book Two", "Author B", "scan-2")

    scans = library.list_all_scans()
    assert len(scans) == 2

    scan_ids = {s["scan_id"] for s in scans}
    assert "scan-1" in scan_ids
    assert "scan-2" in scan_ids


def test_stats_calculation(tmp_path):
    """Test that stats are calculated correctly."""
    library = LibraryStorage(storage_root=tmp_path)

    library.add_book("Book One", "Author A", "scan-1")
    library.update_scan_metadata("scan-1", {"pages": 100, "cost_usd": 5.0})

    library.add_book("Book Two", "Author B", "scan-2")
    library.update_scan_metadata("scan-2", {"pages": 200, "cost_usd": 10.0})

    stats = library.get_stats()
    assert stats["total_books"] == 2
    assert stats["total_scans"] == 2
    assert stats["total_pages"] == 300
    assert stats["total_cost_usd"] == 15.0


def test_delete_scan_with_files(tmp_path):
    """Test deleting a scan including its files."""
    library = LibraryStorage(storage_root=tmp_path)

    # Add a book
    library.add_book("Test Book", "Test Author", "test-scan")

    # Create scan directory with some files
    scan_dir = tmp_path / "test-scan"
    scan_dir.mkdir()
    (scan_dir / "test.txt").write_text("test content")

    # Delete the scan
    result = library.delete_scan("test-scan", delete_files=True)

    assert result["deleted_from_library"] is True
    assert result["files_deleted"] is True
    assert result["book_removed"] is True
    assert not scan_dir.exists()

    # Verify library is updated
    assert len(library.data["books"]) == 0


def test_delete_scan_keep_files(tmp_path):
    """Test deleting a scan but keeping its files."""
    library = LibraryStorage(storage_root=tmp_path)

    # Add a book
    library.add_book("Test Book", "Test Author", "test-scan")

    # Create scan directory
    scan_dir = tmp_path / "test-scan"
    scan_dir.mkdir()
    (scan_dir / "test.txt").write_text("test content")

    # Delete the scan but keep files
    result = library.delete_scan("test-scan", delete_files=False)

    assert result["deleted_from_library"] is True
    assert result["files_deleted"] is False
    assert result["book_removed"] is True
    assert scan_dir.exists()

    # Verify library is updated but files remain
    assert len(library.data["books"]) == 0
    assert (scan_dir / "test.txt").exists()


def test_delete_scan_keep_book(tmp_path):
    """Test deleting one scan but keeping the book (when multiple scans exist)."""
    library = LibraryStorage(storage_root=tmp_path)

    # Add a book with two scans
    library.add_book("Test Book", "Test Author", "test-scan-1")
    library.register_scan("test-book", "test-scan-2")

    # Delete first scan
    result = library.delete_scan("test-scan-1", delete_files=False)

    assert result["deleted_from_library"] is True
    assert result["book_removed"] is False

    # Verify book still exists with one scan
    assert "test-book" in library.data["books"]
    assert len(library.data["books"]["test-book"]["scans"]) == 1
    assert library.data["books"]["test-book"]["scans"][0]["scan_id"] == "test-scan-2"


def test_delete_nonexistent_scan(tmp_path):
    """Test that deleting a non-existent scan raises an error."""
    library = LibraryStorage(storage_root=tmp_path)

    import pytest
    with pytest.raises(ValueError, match="not found"):
        library.delete_scan("nonexistent-scan")


def test_get_book_storage(tmp_path):
    """Test getting a BookStorage instance for a scan."""
    library = LibraryStorage(storage_root=tmp_path)

    # Add a book with a scan
    library.add_book("Test Book", "Test Author", "test-scan")

    # Create scan directory
    scan_dir = tmp_path / "test-scan"
    scan_dir.mkdir()
    (scan_dir / "metadata.json").write_text('{"title": "Test Book"}')

    # Get BookStorage instance
    storage = library.get_book_storage("test-scan")

    # Verify it's a BookStorage instance
    from infra.storage.book_storage import BookStorage
    assert isinstance(storage, BookStorage)
    assert storage.scan_id == "test-scan"
    assert storage.book_dir == scan_dir

    # Verify caching - should return same instance
    storage2 = library.get_book_storage("test-scan")
    assert storage is storage2

    # Test error on non-existent scan
    import pytest
    with pytest.raises(ValueError, match="not found"):
        library.get_book_storage("nonexistent-scan")
