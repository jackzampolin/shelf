"""Tests for tools/library.py"""

import json
from pathlib import Path
from tools.library import LibraryIndex


def test_library_creation(tmp_path):
    """Test that library creates library.json with proper structure."""
    library = LibraryIndex(storage_root=tmp_path)

    library_file = tmp_path / "library.json"
    assert library_file.exists()

    with open(library_file) as f:
        data = json.load(f)
        assert data["version"] == "1.0"
        assert "books" in data
        assert "stats" in data


def test_add_book(tmp_path):
    """Test adding a book to the library."""
    library = LibraryIndex(storage_root=tmp_path)

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
    library = LibraryIndex(storage_root=tmp_path)

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
    library = LibraryIndex(storage_root=tmp_path)

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
    library = LibraryIndex(storage_root=tmp_path)

    library.add_book("Book One", "Author A", "scan-1")
    library.add_book("Book Two", "Author B", "scan-2")

    scans = library.list_all_scans()
    assert len(scans) == 2

    scan_ids = {s["scan_id"] for s in scans}
    assert "scan-1" in scan_ids
    assert "scan-2" in scan_ids


def test_stats_calculation(tmp_path):
    """Test that stats are calculated correctly."""
    library = LibraryIndex(storage_root=tmp_path)

    library.add_book("Book One", "Author A", "scan-1")
    library.update_scan_metadata("scan-1", {"pages": 100, "cost_usd": 5.0})

    library.add_book("Book Two", "Author B", "scan-2")
    library.update_scan_metadata("scan-2", {"pages": 200, "cost_usd": 10.0})

    stats = library.get_stats()
    assert stats["total_books"] == 2
    assert stats["total_scans"] == 2
    assert stats["total_pages"] == 300
    assert stats["total_cost_usd"] == 15.0
