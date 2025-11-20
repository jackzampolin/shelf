"""
ToC Ground Truth Dataset

Utilities for loading and working with ToC extraction ground truth data.
"""

import json
from pathlib import Path
from typing import List, Dict, Any
from dataclasses import dataclass


GT_ROOT = Path(__file__).parent


@dataclass
class GroundTruthBook:
    """Represents a book in the ground truth dataset."""

    scan_id: str
    metadata: Dict[str, Any]
    toc_page_range: Dict[str, int]

    # Paths
    gt_dir: Path
    find_dir: Path
    extract_dir: Path

    # Expected results
    expected_finder_result: Dict[str, Any]
    expected_toc: Dict[str, Any]

    @property
    def total_entries(self) -> int:
        # Try to get total_entries from various locations
        toc_data = self.expected_toc.get("toc", self.expected_toc)
        total = toc_data.get("total_entries")
        if total is not None:
            return total
        # Fall back to counting entries
        entries = toc_data.get("entries", [])
        return len(entries)

    @property
    def entries_by_level(self) -> Dict[str, int]:
        return self.expected_toc.get("toc", {}).get("entries_by_level") or \
               self.expected_toc.get("entries_by_level", {})


def load_book(scan_id: str) -> GroundTruthBook:
    """Load ground truth data for a single book."""
    gt_dir = GT_ROOT / scan_id
    if not gt_dir.exists():
        raise ValueError(f"Ground truth not found for book: {scan_id}")

    # Load metadata
    with open(gt_dir / "metadata.json") as f:
        metadata = json.load(f)

    # Load expected results
    with open(gt_dir / "find" / "expected_result.json") as f:
        expected_finder_result = json.load(f)

    with open(gt_dir / "extract" / "expected_toc.json") as f:
        expected_toc = json.load(f)

    return GroundTruthBook(
        scan_id=scan_id,
        metadata=metadata,
        toc_page_range=metadata["toc_page_range"],
        gt_dir=gt_dir,
        find_dir=gt_dir / "find",
        extract_dir=gt_dir / "extract",
        expected_finder_result=expected_finder_result,
        expected_toc=expected_toc,
    )


def load_all_books() -> List[GroundTruthBook]:
    """Load all books in the ground truth dataset."""
    books = []
    for book_dir in GT_ROOT.iterdir():
        if book_dir.is_dir() and (book_dir / "metadata.json").exists():
            books.append(load_book(book_dir.name))
    return books


def compare_toc(result: Dict[str, Any], expected: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compare a ToC extraction result against ground truth.

    Returns a dict with comparison metrics:
    - total_entries_match: bool
    - entry_count_delta: int
    - entries_match: bool (exact match)
    - ordering_correct: bool (page numbers in ascending order for level-1)
    - title_match_rate: float (0.0-1.0)
    """
    result_toc = result.get("toc", result)
    expected_toc = expected.get("toc", expected)

    result_entries = result_toc.get("entries", [])
    expected_entries = expected_toc.get("entries", [])

    # Total count comparison
    total_match = len(result_entries) == len(expected_entries)
    delta = len(result_entries) - len(expected_entries)

    # Exact entry match
    entries_match = result_entries == expected_entries

    # Check ordering of level-1 entries
    level1_entries = [e for e in result_entries if e.get("level") == 1]
    ordering_correct = is_ascending_page_order(level1_entries)

    # Title match rate (fuzzy comparison)
    title_match_rate = calculate_title_match_rate(result_entries, expected_entries)

    return {
        "total_entries_match": total_match,
        "entry_count_delta": delta,
        "entries_match": entries_match,
        "ordering_correct": ordering_correct,
        "title_match_rate": title_match_rate,
        "result_count": len(result_entries),
        "expected_count": len(expected_entries),
    }


def is_ascending_page_order(entries: List[Dict[str, Any]]) -> bool:
    """Check if level-1 entries are in ascending page number order."""
    page_nums = []
    for entry in entries:
        page = entry.get("printed_page_number")
        if page:
            # Convert roman numerals and regular numbers to int for comparison
            try:
                # For now, just check numeric pages
                if page.isdigit():
                    page_nums.append(int(page))
            except:
                pass

    # Check if sorted (allowing duplicates)
    return page_nums == sorted(page_nums)


def calculate_title_match_rate(
    result: List[Dict[str, Any]],
    expected: List[Dict[str, Any]]
) -> float:
    """Calculate fuzzy title match rate between two entry lists."""
    if not expected:
        return 1.0 if not result else 0.0

    matches = 0
    for i, exp_entry in enumerate(expected):
        if i < len(result):
            res_entry = result[i]
            # Normalize and compare titles
            exp_title = exp_entry.get("title", "").lower().strip()
            res_title = res_entry.get("title", "").lower().strip()
            if exp_title == res_title:
                matches += 1

    return matches / len(expected)


__all__ = [
    "GT_ROOT",
    "GroundTruthBook",
    "load_book",
    "load_all_books",
    "compare_toc",
    "is_ascending_page_order",
    "calculate_title_match_rate",
]
