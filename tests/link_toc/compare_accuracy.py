#!/usr/bin/env python3
"""
Compare link-toc enriched_toc outputs against expected results.

Usage:
    # Compare all books with expected results
    python tests/link_toc/compare_accuracy.py

    # Compare specific book
    python tests/link_toc/compare_accuracy.py --book accidental-president

    # Show only failures
    python tests/link_toc/compare_accuracy.py --failures

    # Verbose output (show all entry differences)
    python tests/link_toc/compare_accuracy.py --verbose
"""

import sys
from pathlib import Path

# Add project root to path for imports
_project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_project_root))

import argparse
from difflib import SequenceMatcher
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field

from infra.pipeline.storage.book_storage import BookStorage
from tests.fixtures.expected.link_toc import (
    load_expected_result,
    list_books,
    ExpectedLinkTocResult
)


# =============================================================================
# CONFIGURATION
# =============================================================================

# Fuzzy matching threshold for titles
FUZZY_TITLE_THRESHOLD = 0.85

# How to weight different aspects of accuracy
TOC_ENTRY_WEIGHT = 0.60       # Original ToC entries (scan_page linkage)
DISCOVERED_WEIGHT = 0.40       # Discovered headings


def normalize_text(text: str) -> str:
    """Normalize text for comparison."""
    if not text:
        return ""

    # Normalize dashes
    text = text.replace('—', '-')  # em-dash
    text = text.replace('–', '-')  # en-dash
    text = text.replace(' - ', '-')

    # Normalize apostrophes
    text = text.replace(''', "'")
    text = text.replace(''', "'")

    # Normalize quotes
    text = text.replace('"', '"')
    text = text.replace('"', '"')

    return text.lower().strip()


def fuzzy_title_match(title1: str, title2: str, threshold: float = FUZZY_TITLE_THRESHOLD) -> Tuple[bool, float]:
    """Compare two titles using fuzzy matching."""
    t1 = normalize_text(title1 or "")
    t2 = normalize_text(title2 or "")

    if t1 == t2:
        return True, 1.0

    similarity = SequenceMatcher(None, t1, t2).ratio()
    return similarity >= threshold, similarity


@dataclass
class EntryComparison:
    """Comparison details for a single entry."""
    index: int
    expected_title: str
    expected_scan_page: int
    actual_title: Optional[str]
    actual_scan_page: Optional[int]
    source: str
    match_type: str  # "exact", "title_only", "page_only", "missing", "extra"
    title_similarity: float = 1.0


@dataclass
class EnrichedTocComparison:
    """Comparison result for enriched_toc."""

    # Counts
    expected_total: int
    actual_total: int
    expected_toc_count: int
    actual_toc_count: int
    expected_discovered: int
    actual_discovered: int

    # Matches by type
    exact_matches: int           # scan_page AND title match
    page_matches: int            # scan_page matches, title close enough
    title_matches: int           # title matches but different page
    missing: int                 # expected but not found
    extra: int                   # found but not expected

    # By source
    toc_exact: int
    toc_page_match: int
    toc_missing: int
    discovered_exact: int
    discovered_page_match: int
    discovered_missing: int

    # Rates
    exact_match_rate: float
    page_match_rate: float       # entries where page is correct
    toc_accuracy: float
    discovered_accuracy: float
    blended_accuracy: float

    # Details
    entry_comparisons: List[EntryComparison] = field(default_factory=list)


@dataclass
class BookComparison:
    """Complete comparison result for one book."""

    book_id: str
    success: bool
    comparison: Optional[EnrichedTocComparison] = None
    error: Optional[str] = None


def find_matching_entry(entry: Dict, candidates: List[Dict], used_indices: set) -> Tuple[Optional[Dict], Optional[int], str, float]:
    """
    Find best matching entry from candidates.

    Returns: (matched_entry, matched_index, match_type, title_similarity)
    """
    scan_page = entry.get("scan_page")
    title = entry.get("title", "")

    best_match = None
    best_idx = None
    best_type = "missing"
    best_similarity = 0.0

    for idx, cand in enumerate(candidates):
        if idx in used_indices:
            continue

        cand_page = cand.get("scan_page")
        cand_title = cand.get("title", "")

        title_match, similarity = fuzzy_title_match(title, cand_title)
        page_match = scan_page == cand_page

        if page_match and title_match:
            # Exact match - best possible
            return cand, idx, "exact", similarity

        if page_match and similarity > best_similarity:
            # Page matches, track best title similarity
            best_match = cand
            best_idx = idx
            best_type = "page_only"
            best_similarity = similarity

        if title_match and best_type == "missing":
            # Title matches but different page
            best_match = cand
            best_idx = idx
            best_type = "title_only"
            best_similarity = similarity

    return best_match, best_idx, best_type, best_similarity


def compare_enriched_toc(expected: ExpectedLinkTocResult, actual: Dict[str, Any]) -> EnrichedTocComparison:
    """Compare enriched_toc outputs."""
    expected_entries = expected.enriched_toc.get("entries", [])
    actual_entries = actual.get("entries", [])

    # Count by source
    expected_toc = [e for e in expected_entries if e.get("source") == "toc"]
    actual_toc = [e for e in actual_entries if e.get("source") == "toc"]
    expected_discovered = [e for e in expected_entries if e.get("source") in ("discovered", "missing_found")]
    actual_discovered = [e for e in actual_entries if e.get("source") in ("discovered", "missing_found")]

    # Track used indices to prevent double-matching
    used_toc_indices = set()
    used_discovered_indices = set()

    entry_comparisons = []

    # Match ToC entries
    toc_exact = 0
    toc_page_match = 0
    toc_missing = 0

    for i, exp in enumerate(expected_toc):
        match, idx, match_type, similarity = find_matching_entry(exp, actual_toc, used_toc_indices)

        if match:
            used_toc_indices.add(idx)

        if match_type == "exact":
            toc_exact += 1
        elif match_type == "page_only":
            toc_page_match += 1
        else:
            toc_missing += 1

        entry_comparisons.append(EntryComparison(
            index=i,
            expected_title=exp.get("title", ""),
            expected_scan_page=exp.get("scan_page"),
            actual_title=match.get("title") if match else None,
            actual_scan_page=match.get("scan_page") if match else None,
            source="toc",
            match_type=match_type,
            title_similarity=similarity,
        ))

    # Match discovered entries
    discovered_exact = 0
    discovered_page_match = 0
    discovered_missing = 0

    for i, exp in enumerate(expected_discovered):
        match, idx, match_type, similarity = find_matching_entry(exp, actual_discovered, used_discovered_indices)

        if match:
            used_discovered_indices.add(idx)

        if match_type == "exact":
            discovered_exact += 1
        elif match_type == "page_only":
            discovered_page_match += 1
        else:
            discovered_missing += 1

        entry_comparisons.append(EntryComparison(
            index=len(expected_toc) + i,
            expected_title=exp.get("title", ""),
            expected_scan_page=exp.get("scan_page"),
            actual_title=match.get("title") if match else None,
            actual_scan_page=match.get("scan_page") if match else None,
            source="discovered",
            match_type=match_type,
            title_similarity=similarity,
        ))

    # Count extras (in actual but not matched)
    toc_extra = len(actual_toc) - len(used_toc_indices)
    discovered_extra = len(actual_discovered) - len(used_discovered_indices)

    # Aggregate stats
    exact_matches = toc_exact + discovered_exact
    page_matches = toc_page_match + discovered_page_match
    title_matches = sum(1 for c in entry_comparisons if c.match_type == "title_only")
    missing = toc_missing + discovered_missing
    extra = toc_extra + discovered_extra

    expected_total = len(expected_entries)
    actual_total = len(actual_entries)

    # Rates
    if expected_total > 0:
        exact_match_rate = exact_matches / expected_total
        page_match_rate = (exact_matches + page_matches) / expected_total
    else:
        exact_match_rate = 1.0
        page_match_rate = 1.0

    if len(expected_toc) > 0:
        toc_accuracy = (toc_exact + toc_page_match) / len(expected_toc)
    else:
        toc_accuracy = 1.0

    if len(expected_discovered) > 0:
        discovered_accuracy = (discovered_exact + discovered_page_match) / len(expected_discovered)
    else:
        discovered_accuracy = 1.0

    blended_accuracy = TOC_ENTRY_WEIGHT * toc_accuracy + DISCOVERED_WEIGHT * discovered_accuracy

    return EnrichedTocComparison(
        expected_total=expected_total,
        actual_total=actual_total,
        expected_toc_count=len(expected_toc),
        actual_toc_count=len(actual_toc),
        expected_discovered=len(expected_discovered),
        actual_discovered=len(actual_discovered),
        exact_matches=exact_matches,
        page_matches=page_matches,
        title_matches=title_matches,
        missing=missing,
        extra=extra,
        toc_exact=toc_exact,
        toc_page_match=toc_page_match,
        toc_missing=toc_missing,
        discovered_exact=discovered_exact,
        discovered_page_match=discovered_page_match,
        discovered_missing=discovered_missing,
        exact_match_rate=exact_match_rate,
        page_match_rate=page_match_rate,
        toc_accuracy=toc_accuracy,
        discovered_accuracy=discovered_accuracy,
        blended_accuracy=blended_accuracy,
        entry_comparisons=entry_comparisons,
    )


def compare_book(book_id: str) -> BookComparison:
    """Compare a book's link-toc output against expected results."""
    try:
        # Load expected
        expected = load_expected_result(book_id)

        # Load actual from library
        storage = BookStorage(book_id)
        stage_storage = storage.stage("link-toc")

        enriched_toc_path = stage_storage.output_dir / "enriched_toc.json"

        if not enriched_toc_path.exists():
            return BookComparison(
                book_id=book_id,
                success=False,
                error="enriched_toc.json not found - stage not complete?"
            )

        actual_enriched = stage_storage.load_file("enriched_toc.json")

        comparison = compare_enriched_toc(expected, actual_enriched)

        # Success = perfect accuracy
        success = (
            comparison.toc_accuracy >= 1.0 and
            comparison.discovered_accuracy >= 1.0
        )

        return BookComparison(
            book_id=book_id,
            success=success,
            comparison=comparison,
        )

    except Exception as e:
        return BookComparison(
            book_id=book_id,
            success=False,
            error=str(e),
        )


def print_book_result(result: BookComparison, verbose: bool = False):
    """Print detailed results for a book."""
    print(f"\n{'='*70}")
    print(f"BOOK: {result.book_id}")
    print(f"{'='*70}")

    if result.error:
        print(f"\n❌ ERROR: {result.error}")
        return

    c = result.comparison
    print(f"\nOVERALL: {'✅ PASS' if result.success else '❌ FAIL'}")
    print(f"BLENDED ACCURACY: {c.blended_accuracy*100:.1f}%")

    print(f"\nENTRIES:")
    print(f"  Total: {c.actual_total}/{c.expected_total}")
    print(f"  ToC: {c.actual_toc_count}/{c.expected_toc_count}")
    print(f"  Discovered: {c.actual_discovered}/{c.expected_discovered}")

    print(f"\nMATCHES:")
    print(f"  Exact (page+title): {c.exact_matches} ({c.exact_match_rate*100:.1f}%)")
    print(f"  Page correct: {c.exact_matches + c.page_matches} ({c.page_match_rate*100:.1f}%)")
    print(f"  Title only: {c.title_matches}")
    print(f"  Missing: {c.missing}")
    print(f"  Extra: {c.extra}")

    print(f"\nBY SOURCE:")
    print(f"  ToC accuracy: {c.toc_accuracy*100:.1f}% ({c.toc_exact} exact, {c.toc_page_match} page, {c.toc_missing} missing)")
    print(f"  Discovered accuracy: {c.discovered_accuracy*100:.1f}% ({c.discovered_exact} exact, {c.discovered_page_match} page, {c.discovered_missing} missing)")

    # Show mismatches
    mismatches = [e for e in c.entry_comparisons if e.match_type not in ("exact",)]
    if mismatches and (verbose or len(mismatches) <= 15):
        print(f"\nMISMATCHES ({len(mismatches)}):")
        for m in mismatches[:30] if not verbose else mismatches:
            if m.match_type == "missing":
                print(f"  [{m.source}] p{m.expected_scan_page}: '{m.expected_title[:40]}' - MISSING")
            elif m.match_type == "page_only":
                print(f"  [{m.source}] p{m.expected_scan_page}: '{m.expected_title[:30]}' vs '{m.actual_title[:30]}' (title {m.title_similarity*100:.0f}%)")
            elif m.match_type == "title_only":
                print(f"  [{m.source}] p{m.expected_scan_page}->p{m.actual_scan_page}: '{m.expected_title[:40]}' - WRONG PAGE")
    elif mismatches:
        print(f"\nMISMATCHES: {len(mismatches)} (use --verbose to see details)")


def compare_all_books(failures_only: bool = False, verbose: bool = False):
    """Compare all books with expected results."""
    book_ids = list_books()

    if not book_ids:
        print("No fixture files found. Generate fixtures first with:")
        print("  python tests/link_toc/generate_fixtures.py --all")
        return

    print(f"\n{'='*70}")
    print(f"LINK-TOC ACCURACY COMPARISON (enriched_toc)")
    print(f"Comparing {len(book_ids)} books against expected results")
    print(f"Weights: ToC={TOC_ENTRY_WEIGHT*100:.0f}%, Discovered={DISCOVERED_WEIGHT*100:.0f}%")
    print(f"{'='*70}")

    results = []
    for book_id in book_ids:
        result = compare_book(book_id)
        results.append(result)

        # Print progress
        status = "✅" if result.success else "❌"
        if result.comparison:
            c = result.comparison
            print(f"  {status} {book_id}: {c.blended_accuracy*100:.0f}% "
                  f"(toc={c.toc_accuracy*100:.0f}%, disc={c.discovered_accuracy*100:.0f}%)")
        else:
            print(f"  {status} {book_id}: ERROR")

    # Summary
    total = len(results)
    perfect = len([r for r in results if r.success])
    errors = len([r for r in results if r.error])

    print(f"\n{'='*70}")
    print(f"SUMMARY")
    print(f"{'='*70}")
    print(f"  Perfect: {perfect}/{total} ({perfect/total*100:.1f}%)")
    print(f"  Errors: {errors}")

    # Averages
    valid_results = [r for r in results if r.comparison]
    if valid_results:
        avg_blended = sum(r.comparison.blended_accuracy for r in valid_results) / len(valid_results)
        avg_toc = sum(r.comparison.toc_accuracy for r in valid_results) / len(valid_results)
        avg_discovered = sum(r.comparison.discovered_accuracy for r in valid_results) / len(valid_results)
        avg_exact = sum(r.comparison.exact_match_rate for r in valid_results) / len(valid_results)

        print(f"\n  AVERAGES:")
        print(f"    Blended Accuracy: {avg_blended*100:.1f}%")
        print(f"    ToC Accuracy: {avg_toc*100:.1f}%")
        print(f"    Discovered Accuracy: {avg_discovered*100:.1f}%")
        print(f"    Exact Match Rate: {avg_exact*100:.1f}%")

    # Show failures
    failures = [r for r in results if not r.success]
    if failures:
        print(f"\n{'='*70}")
        print(f"FAILURES ({len(failures)})")
        print(f"{'='*70}")
        for result in failures:
            if failures_only or verbose:
                print_book_result(result, verbose)
            else:
                if result.error:
                    print(f"  ❌ {result.book_id}: {result.error}")
                elif result.comparison:
                    c = result.comparison
                    print(f"  ❌ {result.book_id}: toc={c.toc_accuracy*100:.0f}%, "
                          f"disc={c.discovered_accuracy*100:.0f}%, "
                          f"missing={c.missing}, extra={c.extra}")

    print()


def main():
    parser = argparse.ArgumentParser(
        description="Compare link-toc enriched_toc outputs against expected results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        "--book",
        help="Compare specific book only"
    )
    parser.add_argument(
        "--failures",
        action="store_true",
        help="Show detailed output for failures only"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show all entry differences"
    )

    args = parser.parse_args()

    if args.book:
        result = compare_book(args.book)
        print_book_result(result, args.verbose)
    else:
        compare_all_books(args.failures, args.verbose)


if __name__ == "__main__":
    main()
