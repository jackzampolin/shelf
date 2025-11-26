"""
Tests for infra/pipeline/storage/library.py

Key behaviors to verify:
1. List books in library
2. Get book info
3. Library stats
4. Book deletion
"""

import json
import pytest
from pathlib import Path
from PIL import Image

from infra.pipeline.storage.library import Library


def create_book(library_root: Path, scan_id: str, metadata: dict, num_pages: int = 5):
    """Helper to create a book in the library."""
    book_dir = library_root / scan_id
    book_dir.mkdir(parents=True)

    # Write metadata
    with open(book_dir / "metadata.json", "w") as f:
        json.dump(metadata, f)

    # Create source directory with dummy images
    source_dir = book_dir / "source"
    source_dir.mkdir()
    for i in range(1, num_pages + 1):
        img = Image.new('RGB', (100, 100), color='white')
        img.save(source_dir / f"page_{i:04d}.png")

    return book_dir


class TestLibraryListBooks:
    """Test book listing functionality."""

    def test_list_books_empty_library(self, tmp_library):
        """Empty library should return empty list."""
        lib = Library(storage_root=tmp_library)

        books = lib.list_books()

        assert books == []

    def test_list_books_single_book(self, tmp_library):
        """Library with one book should return that book."""
        create_book(tmp_library, "my-book", {
            "title": "My Book",
            "author": "John Doe",
            "year": 2024,
            "total_pages": 10
        })

        lib = Library(storage_root=tmp_library)
        books = lib.list_books()

        assert len(books) == 1
        assert books[0]["scan_id"] == "my-book"
        assert books[0]["title"] == "My Book"
        assert books[0]["author"] == "John Doe"

    def test_list_books_multiple_books(self, tmp_library):
        """Library should list all books sorted by scan_id."""
        create_book(tmp_library, "zebra-book", {"title": "Zebra"})
        create_book(tmp_library, "alpha-book", {"title": "Alpha"})
        create_book(tmp_library, "beta-book", {"title": "Beta"})

        lib = Library(storage_root=tmp_library)
        books = lib.list_books()

        scan_ids = [b["scan_id"] for b in books]
        assert scan_ids == ["alpha-book", "beta-book", "zebra-book"]

    def test_list_books_ignores_hidden_dirs(self, tmp_library):
        """Library should ignore hidden directories."""
        create_book(tmp_library, "real-book", {"title": "Real"})
        (tmp_library / ".hidden-book").mkdir()

        lib = Library(storage_root=tmp_library)
        books = lib.list_books()

        assert len(books) == 1
        assert books[0]["scan_id"] == "real-book"


class TestLibraryGetBookStorage:
    """Test get_book_storage functionality."""

    def test_get_book_storage_returns_storage(self, tmp_library):
        """get_book_storage should return BookStorage instance."""
        create_book(tmp_library, "my-book", {"title": "Test"})

        lib = Library(storage_root=tmp_library)
        storage = lib.get_book_storage("my-book")

        assert storage.scan_id == "my-book"

    def test_get_book_storage_caches(self, tmp_library):
        """get_book_storage should cache and return same instance."""
        create_book(tmp_library, "my-book", {"title": "Test"})

        lib = Library(storage_root=tmp_library)
        storage1 = lib.get_book_storage("my-book")
        storage2 = lib.get_book_storage("my-book")

        assert storage1 is storage2

    def test_get_book_storage_nonexistent_raises(self, tmp_library):
        """get_book_storage for nonexistent book should raise."""
        lib = Library(storage_root=tmp_library)

        with pytest.raises(ValueError, match="not found"):
            lib.get_book_storage("nonexistent")


class TestLibraryGetScanInfo:
    """Test get_scan_info functionality."""

    def test_get_scan_info(self, tmp_library):
        """get_scan_info should return detailed book info."""
        create_book(tmp_library, "my-book", {
            "title": "My Title",
            "author": "Author Name",
            "year": 2024,
            "total_pages": 100
        })

        lib = Library(storage_root=tmp_library)
        info = lib.get_scan_info("my-book")

        assert info["scan_id"] == "my-book"
        assert info["title"] == "My Title"
        assert info["author"] == "Author Name"
        assert info["year"] == 2024

    def test_get_scan_info_nonexistent(self, tmp_library):
        """get_scan_info for nonexistent book should return None."""
        lib = Library(storage_root=tmp_library)

        info = lib.get_scan_info("nonexistent")

        assert info is None


class TestLibraryStats:
    """Test library statistics."""

    def test_get_stats_empty(self, tmp_library):
        """Empty library should have zero stats."""
        lib = Library(storage_root=tmp_library)

        stats = lib.get_stats()

        assert stats["total_books"] == 0
        assert stats["total_pages"] == 0

    def test_get_stats_with_books(self, tmp_library):
        """Stats should aggregate across all books."""
        create_book(tmp_library, "book1", {"total_pages": 100})
        create_book(tmp_library, "book2", {"total_pages": 200})
        create_book(tmp_library, "book3", {"total_pages": 50})

        lib = Library(storage_root=tmp_library)
        stats = lib.get_stats()

        assert stats["total_books"] == 3
        assert stats["total_pages"] == 350


class TestLibraryDeleteBook:
    """Test book deletion."""

    def test_delete_book(self, tmp_library):
        """delete_book should remove book directory."""
        book_dir = create_book(tmp_library, "to-delete", {"title": "Delete Me"})
        assert book_dir.exists()

        lib = Library(storage_root=tmp_library)
        lib.delete_book("to-delete")

        assert not book_dir.exists()

    def test_delete_book_clears_cache(self, tmp_library):
        """delete_book should clear the storage cache."""
        create_book(tmp_library, "cached-book", {"title": "Cached"})

        lib = Library(storage_root=tmp_library)
        # Access to populate cache
        lib.get_book_storage("cached-book")
        assert "cached-book" in lib._book_storage_cache

        lib.delete_book("cached-book")

        assert "cached-book" not in lib._book_storage_cache

    def test_delete_nonexistent_raises(self, tmp_library):
        """delete_book for nonexistent book should raise."""
        lib = Library(storage_root=tmp_library)

        with pytest.raises(ValueError, match="not found"):
            lib.delete_book("nonexistent")
