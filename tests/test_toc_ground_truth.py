"""
Tests for ToC extraction against ground truth dataset.

Usage:
    pytest tests/test_toc_ground_truth.py -v
    pytest tests/test_toc_ground_truth.py::test_ordering_correctness -v
"""

import pytest
from tests.fixtures.toc_ground_truth import (
    load_all_books,
    load_book,
    compare_toc,
    is_ascending_page_order,
)


@pytest.fixture
def all_ground_truth_books():
    """Load all ground truth books."""
    return load_all_books()


def test_ground_truth_loads():
    """Test that ground truth data loads correctly."""
    books = load_all_books()
    assert len(books) >= 5, f"Expected at least 5 books, found {len(books)}"

    for book in books:
        assert book.scan_id
        assert book.metadata
        assert book.expected_toc
        assert book.expected_finder_result


def test_ordering_correctness(all_ground_truth_books):
    """Test that all ground truth ToCs have correct page ordering."""
    for book in all_ground_truth_books:
        toc = book.expected_toc.get("toc", book.expected_toc)
        entries = toc.get("entries", [])
        level1_entries = [e for e in entries if e.get("level") == 1]

        assert is_ascending_page_order(level1_entries), \
            f"{book.scan_id}: Level-1 entries not in ascending page order"


def test_structure_completeness(all_ground_truth_books):
    """Test that all ground truth books have complete structure."""
    for book in all_ground_truth_books:
        # Check standard book structure
        assert (book.gt_dir / "metadata.json").exists()
        assert (book.gt_dir / "source").exists()
        assert (book.gt_dir / "ocr-pages" / "paddle").exists()
        assert (book.gt_dir / "ocr-pages" / "mistral").exists()
        assert (book.gt_dir / "ocr-pages" / "olm").exists()

        # Check expected outputs
        assert (book.expected_dir / "find" / "finder_result.json").exists()
        assert (book.expected_dir / "finalize" / "toc.json").exists()

        # Check first 50 pages exist (for find phase)
        for page in range(1, 51):
            page_str = f"{page:04d}"
            # At least paddle OCR should exist
            assert (book.gt_dir / "ocr-pages" / "paddle" / f"page_{page_str}.json").exists(), \
                f"{book.scan_id}: Missing paddle OCR for page {page}"


def test_metadata_consistency(all_ground_truth_books):
    """Test that metadata matches extracted ToC."""
    for book in all_ground_truth_books:
        metadata_total = book.metadata.get("total_entries")
        toc_total = book.total_entries

        if metadata_total is not None:
            assert metadata_total == toc_total, \
                f"{book.scan_id}: Metadata total ({metadata_total}) != ToC total ({toc_total})"


@pytest.mark.parametrize("book_id", [
    "fiery-peace",
    "admirals",
    "groves-bomb",
    "american-caesar",
    "hap-arnold",
])
def test_individual_book_loads(book_id):
    """Test that each book can be loaded individually."""
    book = load_book(book_id)
    assert book.scan_id == book_id
    assert book.total_entries > 0


def test_compare_toc_identical():
    """Test that comparing identical ToCs returns perfect match."""
    book = load_book("fiery-peace")
    result = compare_toc(book.expected_toc, book.expected_toc)

    assert result["total_entries_match"] is True
    assert result["entry_count_delta"] == 0
    assert result["entries_match"] is True
    assert result["ordering_correct"] is True
    assert result["title_match_rate"] == 1.0


def test_compare_toc_detects_differences():
    """Test that compare_toc detects differences."""
    book = load_book("fiery-peace")
    expected = book.expected_toc

    # Create a modified version
    modified = expected.copy()
    modified_toc = modified.get("toc", modified).copy()
    modified_entries = modified_toc["entries"][:10]  # Take only first 10 entries
    modified_toc["entries"] = modified_entries
    modified["toc"] = modified_toc

    result = compare_toc(modified, expected)

    assert result["total_entries_match"] is False
    assert result["entry_count_delta"] < 0
    assert result["entries_match"] is False


if __name__ == "__main__":
    # Quick manual test
    books = load_all_books()
    print(f"Loaded {len(books)} ground truth books:")
    for book in books:
        print(f"  {book.scan_id}: {book.total_entries} entries, "
              f"ToC pages {book.toc_page_range['start_page']}-{book.toc_page_range['end_page']}")
        print(f"    Levels: {book.entries_by_level}")
