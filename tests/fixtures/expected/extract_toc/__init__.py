"""
Expected results for extract-toc accuracy tests.

Provides ground truth results for comparing extract-toc stage outputs.
"""

import json
from pathlib import Path
from typing import Dict, Any, List
from dataclasses import dataclass


EXPECTED_DIR = Path(__file__).parent


@dataclass
class ExpectedExtractTocResult:
    """Expected results for extract-toc stage."""

    scan_id: str
    finder_result: Dict[str, Any]
    toc: Dict[str, Any]

    @property
    def total_entries(self) -> int:
        """Get total number of ToC entries."""
        toc_data = self.toc.get("toc", self.toc)
        entries = toc_data.get("entries", [])
        return len(entries)

    @property
    def toc_page_range(self) -> Dict[str, int]:
        """Get ToC page range from finder result."""
        return self.finder_result.get("toc_page_range", {})


def load_expected_result(book_id: str) -> ExpectedExtractTocResult:
    """
    Load expected extract-toc results for a book.

    Args:
        book_id: Book scan ID

    Returns:
        ExpectedExtractTocResult with ground truth data

    Raises:
        ValueError: If expected results not found for book
    """
    expected_file = EXPECTED_DIR / f"{book_id}.json"

    if not expected_file.exists():
        raise ValueError(f"No expected results found for book: {book_id}")

    with open(expected_file) as f:
        data = json.load(f)

    return ExpectedExtractTocResult(
        scan_id=data["scan_id"],
        finder_result=data["finder_result"],
        toc=data["toc"]
    )


def load_all_expected_results() -> List[ExpectedExtractTocResult]:
    """
    Load expected results for all books.

    Returns:
        List of ExpectedExtractTocResult
    """
    results = []

    for expected_file in sorted(EXPECTED_DIR.glob("*.json")):
        book_id = expected_file.stem
        results.append(load_expected_result(book_id))

    return results


def list_books() -> List[str]:
    """
    List all books with expected results.

    Returns:
        List of book IDs
    """
    return sorted([f.stem for f in EXPECTED_DIR.glob("*.json")])


__all__ = [
    "ExpectedExtractTocResult",
    "load_expected_result",
    "load_all_expected_results",
    "list_books",
]
