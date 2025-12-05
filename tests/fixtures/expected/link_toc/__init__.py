"""
Expected results for link-toc accuracy tests.

Provides ground truth results for comparing link-toc stage outputs.
Focuses on enriched_toc which is the final output containing both
ToC entries and discovered headings.
"""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass


EXPECTED_DIR = Path(__file__).parent


@dataclass
class ExpectedEnrichedEntry:
    """Expected enriched ToC entry."""

    title: str
    scan_page: int
    level: int
    source: str  # "toc", "discovered", "missing_found"
    entry_number: Optional[str] = None
    printed_page_number: Optional[str] = None


@dataclass
class ExpectedLinkTocResult:
    """Expected results for link-toc stage (enriched_toc only)."""

    scan_id: str
    enriched_toc: Dict[str, Any]

    @property
    def entries(self) -> List[ExpectedEnrichedEntry]:
        """Get enriched ToC entries as typed objects."""
        entries = self.enriched_toc.get("entries", [])
        return [
            ExpectedEnrichedEntry(
                title=e.get("title", ""),
                scan_page=e.get("scan_page"),
                level=e.get("level", 1),
                source=e.get("source", "toc"),
                entry_number=e.get("entry_number"),
                printed_page_number=e.get("printed_page_number"),
            )
            for e in entries
        ]

    @property
    def total_entries(self) -> int:
        """Get total number of enriched ToC entries."""
        return self.enriched_toc.get("total_entries", len(self.enriched_toc.get("entries", [])))

    @property
    def toc_count(self) -> int:
        """Get number of original ToC entries."""
        return self.enriched_toc.get("original_toc_count", 0)

    @property
    def discovered_count(self) -> int:
        """Get number of discovered headings."""
        return self.enriched_toc.get("discovered_count", 0)


def load_expected_result(book_id: str) -> ExpectedLinkTocResult:
    """
    Load expected link-toc results for a book.

    Args:
        book_id: Book scan ID

    Returns:
        ExpectedLinkTocResult with ground truth data

    Raises:
        ValueError: If expected results not found for book
    """
    expected_file = EXPECTED_DIR / f"{book_id}.json"

    if not expected_file.exists():
        raise ValueError(f"No expected results found for book: {book_id}")

    with open(expected_file) as f:
        data = json.load(f)

    return ExpectedLinkTocResult(
        scan_id=data["scan_id"],
        enriched_toc=data["enriched_toc"]
    )


def load_all_expected_results() -> List[ExpectedLinkTocResult]:
    """
    Load expected results for all books.

    Returns:
        List of ExpectedLinkTocResult
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
    "ExpectedEnrichedEntry",
    "ExpectedLinkTocResult",
    "load_expected_result",
    "load_all_expected_results",
    "list_books",
]
