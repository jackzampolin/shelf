#!/usr/bin/env python3
"""
Compare link-toc outputs in the library against expected results.

Compares both linked_toc (scan_page mappings) and enriched_toc (discovered headings).

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
import json
from difflib import SequenceMatcher
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from infra.pipeline.storage.book_storage import BookStorage
from tests.fixtures.expected.link_toc import (
    load_all_expected_results,
    load_expected_result,
    list_books,
    ExpectedLinkTocResult
)


# =============================================================================
# ACCURACY WEIGHTS (can be tuned later)
# =============================================================================

# Linked ToC weights
LINKING_WEIGHT = 0.70           # Did we link entries to correct scan pages?
COMPLETENESS_WEIGHT = 0.15      # Did we link all entries (vs leaving null)?
DISCOVERY_WEIGHT = 0.15         # Did we discover the right headings?

# Within linking accuracy:
EXACT_MATCH_WEIGHT = 0.80       # Exact scan_page match
CLOSE_MATCH_WEIGHT = 0.20       # Within N pages (tolerance for ambiguous starts)
CLOSE_MATCH_TOLERANCE = 2       # Pages within this tolerance count as "close"

# Fuzzy matching threshold for titles
FUZZY_TITLE_THRESHOLD = 0.85


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


def fuzzy_title_match(title1: str, title2: str, threshold: float = FUZZY_TITLE_THRESHOLD) -> tuple[bool, float]:
    """Compare two titles using fuzzy matching."""
    t1 = normalize_text(title1 or "")
    t2 = normalize_text(title2 or "")

    if t1 == t2:
        return True, 1.0

    similarity = SequenceMatcher(None, t1, t2).ratio()
    return similarity >= threshold, similarity


@dataclass
class LinkedTocComparison:
    """Comparison result for linked_toc phase."""

    # Entry-level stats
    total_expected: int
    total_actual: int
    entry_count_match: bool

    # Scan page linking accuracy
    exact_matches: int           # scan_page exactly correct
    close_matches: int           # scan_page within tolerance
    wrong_matches: int           # scan_page incorrect
    missing_links: int           # expected link but got null
    extra_links: int             # expected null but got link

    # Computed rates
    exact_match_rate: float
    close_match_rate: float
    link_completeness: float     # entries with scan_page / total

    # Blended score
    linking_accuracy: float

    # Details for debugging
    mismatches: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class EnrichedTocComparison:
    """Comparison result for enriched_toc phase."""

    # Entry counts
    expected_total: int
    actual_total: int
    expected_toc_count: int
    actual_toc_count: int
    expected_discovered: int
    actual_discovered: int

    # Match rates
    toc_entries_matched: int
    discovered_entries_matched: int

    # Computed rates
    toc_match_rate: float
    discovered_match_rate: float
    total_match_rate: float

    # Details
    missing_entries: List[Dict[str, Any]] = field(default_factory=list)
    extra_entries: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class BookComparison:
    """Complete comparison result for one book."""

    book_id: str
    success: bool
    linked_toc: Optional[LinkedTocComparison] = None
    enriched_toc: Optional[EnrichedTocComparison] = None
    blended_accuracy: float = 0.0
    error: Optional[str] = None


def compare_linked_toc(expected: ExpectedLinkTocResult, actual: Dict[str, Any]) -> LinkedTocComparison:
    """Compare linked_toc outputs."""
    expected_entries = expected.linked_toc.get("entries", [])
    actual_entries = actual.get("entries", [])

    # Filter out None entries
    actual_entries = [e for e in actual_entries if e is not None]

    total_expected = len(expected_entries)
    total_actual = len(actual_entries)
    entry_count_match = total_expected == total_actual

    # Compare entries by index
    exact_matches = 0
    close_matches = 0
    wrong_matches = 0
    missing_links = 0
    extra_links = 0
    mismatches = []

    matched_count = min(total_expected, total_actual)

    for i in range(matched_count):
        exp = expected_entries[i]
        act = actual_entries[i]

        exp_page = exp.get("scan_page")
        act_page = act.get("scan_page")

        if exp_page is None and act_page is None:
            # Both null - match
            exact_matches += 1
        elif exp_page is None and act_page is not None:
            # Expected null, got link
            extra_links += 1
            mismatches.append({
                "index": i,
                "title": exp.get("title"),
                "issue": "extra_link",
                "expected": None,
                "actual": act_page,
            })
        elif exp_page is not None and act_page is None:
            # Expected link, got null
            missing_links += 1
            mismatches.append({
                "index": i,
                "title": exp.get("title"),
                "issue": "missing_link",
                "expected": exp_page,
                "actual": None,
            })
        elif exp_page == act_page:
            # Exact match
            exact_matches += 1
        elif abs(exp_page - act_page) <= CLOSE_MATCH_TOLERANCE:
            # Close match
            close_matches += 1
            mismatches.append({
                "index": i,
                "title": exp.get("title"),
                "issue": "close_match",
                "expected": exp_page,
                "actual": act_page,
                "diff": act_page - exp_page,
            })
        else:
            # Wrong match
            wrong_matches += 1
            mismatches.append({
                "index": i,
                "title": exp.get("title"),
                "issue": "wrong_page",
                "expected": exp_page,
                "actual": act_page,
                "diff": act_page - exp_page,
            })

    # Track missing/extra entries
    for i in range(matched_count, total_expected):
        mismatches.append({
            "index": i,
            "title": expected_entries[i].get("title"),
            "issue": "missing_entry",
        })

    for i in range(total_expected, total_actual):
        mismatches.append({
            "index": i,
            "title": actual_entries[i].get("title"),
            "issue": "extra_entry",
        })

    # Compute rates
    if total_expected > 0:
        exact_match_rate = exact_matches / total_expected
        close_match_rate = (exact_matches + close_matches) / total_expected
    else:
        exact_match_rate = 1.0
        close_match_rate = 1.0

    # Link completeness (how many expected links were found)
    expected_with_links = sum(1 for e in expected_entries if e.get("scan_page") is not None)
    actual_with_links = sum(1 for e in actual_entries if e.get("scan_page") is not None)

    if expected_with_links > 0:
        link_completeness = min(actual_with_links, expected_with_links) / expected_with_links
    else:
        link_completeness = 1.0

    # Blended linking accuracy
    linking_accuracy = (
        EXACT_MATCH_WEIGHT * exact_match_rate +
        CLOSE_MATCH_WEIGHT * close_match_rate
    )

    return LinkedTocComparison(
        total_expected=total_expected,
        total_actual=total_actual,
        entry_count_match=entry_count_match,
        exact_matches=exact_matches,
        close_matches=close_matches,
        wrong_matches=wrong_matches,
        missing_links=missing_links,
        extra_links=extra_links,
        exact_match_rate=exact_match_rate,
        close_match_rate=close_match_rate,
        link_completeness=link_completeness,
        linking_accuracy=linking_accuracy,
        mismatches=mismatches,
    )


def compare_enriched_toc(expected: ExpectedLinkTocResult, actual: Dict[str, Any]) -> EnrichedTocComparison:
    """Compare enriched_toc outputs."""
    expected_entries = expected.enriched_toc.get("entries", [])
    actual_entries = actual.get("entries", [])

    expected_total = len(expected_entries)
    actual_total = len(actual_entries)

    # Count by source
    expected_toc = [e for e in expected_entries if e.get("source") == "toc"]
    actual_toc = [e for e in actual_entries if e.get("source") == "toc"]
    expected_discovered = [e for e in expected_entries if e.get("source") in ("discovered", "missing_found")]
    actual_discovered = [e for e in actual_entries if e.get("source") in ("discovered", "missing_found")]

    # Match entries by (scan_page, fuzzy_title)
    def find_match(entry: Dict, candidates: List[Dict]) -> Optional[Dict]:
        """Find matching entry by scan_page and fuzzy title."""
        scan_page = entry.get("scan_page")
        title = entry.get("title", "")

        for cand in candidates:
            if cand.get("scan_page") == scan_page:
                is_match, _ = fuzzy_title_match(title, cand.get("title", ""))
                if is_match:
                    return cand
        return None

    # Match ToC entries
    toc_matched = 0
    for exp in expected_toc:
        if find_match(exp, actual_toc):
            toc_matched += 1

    # Match discovered entries
    discovered_matched = 0
    for exp in expected_discovered:
        if find_match(exp, actual_discovered):
            discovered_matched += 1

    # Find missing and extra
    missing_entries = []
    for exp in expected_entries:
        if not find_match(exp, actual_entries):
            missing_entries.append({
                "title": exp.get("title"),
                "scan_page": exp.get("scan_page"),
                "source": exp.get("source"),
            })

    extra_entries = []
    for act in actual_entries:
        if not find_match(act, expected_entries):
            extra_entries.append({
                "title": act.get("title"),
                "scan_page": act.get("scan_page"),
                "source": act.get("source"),
            })

    # Compute rates
    toc_match_rate = toc_matched / len(expected_toc) if expected_toc else 1.0
    discovered_match_rate = discovered_matched / len(expected_discovered) if expected_discovered else 1.0
    total_match_rate = (toc_matched + discovered_matched) / expected_total if expected_total > 0 else 1.0

    return EnrichedTocComparison(
        expected_total=expected_total,
        actual_total=actual_total,
        expected_toc_count=len(expected_toc),
        actual_toc_count=len(actual_toc),
        expected_discovered=len(expected_discovered),
        actual_discovered=len(actual_discovered),
        toc_entries_matched=toc_matched,
        discovered_entries_matched=discovered_matched,
        toc_match_rate=toc_match_rate,
        discovered_match_rate=discovered_match_rate,
        total_match_rate=total_match_rate,
        missing_entries=missing_entries,
        extra_entries=extra_entries,
    )


def compare_book(book_id: str) -> BookComparison:
    """Compare a book's link-toc output against expected results."""
    try:
        # Load expected
        expected = load_expected_result(book_id)

        # Load actual from library
        storage = BookStorage(book_id)
        stage_storage = storage.stage("link-toc")

        # Check if outputs exist
        linked_toc_path = stage_storage.output_dir / "linked_toc.json"
        enriched_toc_path = stage_storage.output_dir / "enriched_toc.json"

        if not linked_toc_path.exists():
            return BookComparison(
                book_id=book_id,
                success=False,
                error="linked_toc.json not found - stage not run?"
            )

        if not enriched_toc_path.exists():
            return BookComparison(
                book_id=book_id,
                success=False,
                error="enriched_toc.json not found - merge phase not complete?"
            )

        # Load actual results
        actual_linked = stage_storage.load_file("linked_toc.json")
        actual_enriched = stage_storage.load_file("enriched_toc.json")

        # Compare
        linked_comparison = compare_linked_toc(expected, actual_linked)
        enriched_comparison = compare_enriched_toc(expected, actual_enriched)

        # Blended accuracy
        blended_accuracy = (
            LINKING_WEIGHT * linked_comparison.linking_accuracy +
            COMPLETENESS_WEIGHT * linked_comparison.link_completeness +
            DISCOVERY_WEIGHT * enriched_comparison.total_match_rate
        )

        # Success = high accuracy (can tune threshold)
        success = (
            linked_comparison.exact_match_rate >= 0.95 and
            linked_comparison.link_completeness >= 0.95 and
            enriched_comparison.toc_match_rate >= 0.95
        )

        return BookComparison(
            book_id=book_id,
            success=success,
            linked_toc=linked_comparison,
            enriched_toc=enriched_comparison,
            blended_accuracy=blended_accuracy,
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
        print(f"\n  ERROR: {result.error}")
        return

    print(f"\nOVERALL: {'PASS' if result.success else 'FAIL'}")
    print(f"BLENDED ACCURACY: {result.blended_accuracy*100:.1f}%")

    # Linked ToC
    if result.linked_toc:
        lt = result.linked_toc
        print(f"\nLINKED_TOC:")
        print(f"  Entries: {lt.total_actual}/{lt.total_expected}")
        print(f"  Exact matches: {lt.exact_matches} ({lt.exact_match_rate*100:.1f}%)")
        print(f"  Close matches: {lt.close_matches} (within {CLOSE_MATCH_TOLERANCE} pages)")
        print(f"  Wrong pages: {lt.wrong_matches}")
        print(f"  Missing links: {lt.missing_links}")
        print(f"  Extra links: {lt.extra_links}")
        print(f"  Link completeness: {lt.link_completeness*100:.1f}%")
        print(f"  Linking accuracy: {lt.linking_accuracy*100:.1f}%")

        if lt.mismatches and (verbose or len(lt.mismatches) <= 10):
            print(f"\n  Mismatches ({len(lt.mismatches)}):")
            for m in lt.mismatches[:20] if not verbose else lt.mismatches:
                issue = m.get("issue")
                title = m.get("title", "")[:40]
                if issue == "wrong_page":
                    print(f"    #{m['index']}: '{title}' - expected p{m['expected']}, got p{m['actual']} (diff: {m['diff']:+d})")
                elif issue == "close_match":
                    print(f"    #{m['index']}: '{title}' - expected p{m['expected']}, got p{m['actual']} (close, diff: {m['diff']:+d})")
                elif issue == "missing_link":
                    print(f"    #{m['index']}: '{title}' - expected p{m['expected']}, got null")
                elif issue == "extra_link":
                    print(f"    #{m['index']}: '{title}' - expected null, got p{m['actual']}")
                elif issue == "missing_entry":
                    print(f"    #{m['index']}: '{title}' - entry missing from actual")
                elif issue == "extra_entry":
                    print(f"    #{m['index']}: '{title}' - extra entry in actual")
        elif lt.mismatches:
            print(f"\n  Mismatches: {len(lt.mismatches)} (use --verbose to see details)")

    # Enriched ToC
    if result.enriched_toc:
        et = result.enriched_toc
        print(f"\nENRICHED_TOC:")
        print(f"  Total entries: {et.actual_total}/{et.expected_total}")
        print(f"  ToC entries: {et.actual_toc_count}/{et.expected_toc_count} (matched: {et.toc_entries_matched})")
        print(f"  Discovered: {et.actual_discovered}/{et.expected_discovered} (matched: {et.discovered_entries_matched})")
        print(f"  ToC match rate: {et.toc_match_rate*100:.1f}%")
        print(f"  Discovered match rate: {et.discovered_match_rate*100:.1f}%")
        print(f"  Total match rate: {et.total_match_rate*100:.1f}%")

        if et.missing_entries and (verbose or len(et.missing_entries) <= 5):
            print(f"\n  Missing entries ({len(et.missing_entries)}):")
            for m in et.missing_entries[:10]:
                print(f"    p{m['scan_page']}: '{m['title'][:40]}' ({m['source']})")

        if et.extra_entries and (verbose or len(et.extra_entries) <= 5):
            print(f"\n  Extra entries ({len(et.extra_entries)}):")
            for m in et.extra_entries[:10]:
                print(f"    p{m['scan_page']}: '{m['title'][:40]}' ({m['source']})")


def compare_all_books(failures_only: bool = False, verbose: bool = False):
    """Compare all books with expected results."""
    book_ids = list_books()

    if not book_ids:
        print("No fixture files found. Generate fixtures first with:")
        print("  python tests/link_toc/generate_fixtures.py --all")
        return

    print(f"\n{'='*70}")
    print(f"LINK-TOC ACCURACY COMPARISON")
    print(f"Comparing {len(book_ids)} books against expected results")
    print(f"Weights: Linking={LINKING_WEIGHT*100:.0f}%, Completeness={COMPLETENESS_WEIGHT*100:.0f}%, Discovery={DISCOVERY_WEIGHT*100:.0f}%")
    print(f"{'='*70}")

    results = []
    for book_id in book_ids:
        result = compare_book(book_id)
        results.append(result)

        # Print progress
        status = "PASS" if result.success else "FAIL"
        if result.linked_toc:
            blended = f"{result.blended_accuracy*100:.0f}%"
            exact = f"{result.linked_toc.exact_match_rate*100:.0f}%"
        else:
            blended = "N/A"
            exact = "N/A"
        print(f"  {status} {book_id}: {blended} (exact: {exact})")

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
    valid_results = [r for r in results if r.linked_toc]
    if valid_results:
        avg_blended = sum(r.blended_accuracy for r in valid_results) / len(valid_results)
        avg_exact = sum(r.linked_toc.exact_match_rate for r in valid_results) / len(valid_results)
        avg_completeness = sum(r.linked_toc.link_completeness for r in valid_results) / len(valid_results)

        print(f"\n  AVERAGES:")
        print(f"    Blended Accuracy: {avg_blended*100:.1f}%")
        print(f"    Exact Match Rate: {avg_exact*100:.1f}%")
        print(f"    Link Completeness: {avg_completeness*100:.1f}%")

        if any(r.enriched_toc for r in valid_results):
            enriched_results = [r for r in valid_results if r.enriched_toc]
            avg_toc_match = sum(r.enriched_toc.toc_match_rate for r in enriched_results) / len(enriched_results)
            avg_discovery = sum(r.enriched_toc.discovered_match_rate for r in enriched_results) / len(enriched_results)
            print(f"    ToC Match Rate: {avg_toc_match*100:.1f}%")
            print(f"    Discovery Match Rate: {avg_discovery*100:.1f}%")

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
                    print(f"  FAIL {result.book_id}: {result.error}")
                elif result.linked_toc:
                    lt = result.linked_toc
                    print(f"  FAIL {result.book_id}: exact={lt.exact_match_rate*100:.0f}%, "
                          f"wrong={lt.wrong_matches}, missing={lt.missing_links}")

    print()


def main():
    parser = argparse.ArgumentParser(
        description="Compare link-toc outputs against expected results",
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
