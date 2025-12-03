#!/usr/bin/env python3
"""
Compare extract-toc outputs in the library against expected results.

Usage:
    # Compare all books with expected results
    python tests/extract_toc/compare_accuracy.py

    # Compare specific book
    python tests/extract_toc/compare_accuracy.py --book accidental-president

    # Show only failures
    python tests/extract_toc/compare_accuracy.py --failures

    # Verbose output (show all entry differences)
    python tests/extract_toc/compare_accuracy.py --verbose
"""

import sys
from pathlib import Path

# Add project root to path for imports
_project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_project_root))

import argparse
import json
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from infra.pipeline.storage.book_storage import BookStorage
from tests.fixtures.expected.extract_toc import (
    load_all_expected_results,
    load_expected_result,
    list_books,
    ExpectedExtractTocResult
)


def normalize_text(text: str) -> str:
    """
    Normalize text for comparison by standardizing typographic variations.

    Converts:
    - Em-dashes (—) and en-dashes (–) to hyphens (-)
    - Spaced hyphens ( - ) to hyphens (-)
    - Curly apostrophes (' ') to straight apostrophes (')
    - Curly quotes (" ") to straight quotes (")
    """
    if not text:
        return text

    # Normalize dashes
    text = text.replace('—', '-')  # em-dash
    text = text.replace('–', '-')  # en-dash
    text = text.replace(' - ', '-')  # spaced hyphen

    # Normalize apostrophes
    text = text.replace(''', "'")  # right single quote (U+2019)
    text = text.replace(''', "'")  # left single quote (U+2018)
    text = text.replace('\u2019', "'")  # right single quote explicit
    text = text.replace('\u2018', "'")  # left single quote explicit

    # Normalize quotes
    text = text.replace('"', '"')  # left double quote (U+201C)
    text = text.replace('"', '"')  # right double quote (U+201D)
    text = text.replace('\u201c', '"')  # left double quote explicit
    text = text.replace('\u201d', '"')  # right double quote explicit

    return text


@dataclass
class FindPhaseComparison:
    """Comparison result for find phase."""
    matches: bool
    toc_found_match: bool
    page_range_match: bool
    expected_range: Dict[str, int]
    actual_range: Optional[Dict[str, int]]
    differences: List[str] = field(default_factory=list)


@dataclass
class ExtractPhaseComparison:
    """Comparison result for extract phase."""
    matches: bool
    entry_count_match: bool
    perfect_entry_match: bool
    expected_count: int
    actual_count: int
    title_match_rate: float
    entry_match_rate: float
    mismatched_entries: List[Dict[str, Any]] = field(default_factory=list)
    differences: List[str] = field(default_factory=list)


@dataclass
class BookComparison:
    """Complete comparison result for one book."""
    book_id: str
    success: bool
    find_phase: Optional[FindPhaseComparison] = None
    extract_phase: Optional[ExtractPhaseComparison] = None
    error: Optional[str] = None


def compare_find_phase(expected: ExpectedExtractTocResult, actual_finder: Dict[str, Any]) -> FindPhaseComparison:
    """Compare find phase output to expected."""
    exp_finder = expected.finder_result
    differences = []

    # Compare toc_found
    toc_found_match = exp_finder.get("toc_found") == actual_finder.get("toc_found")
    if not toc_found_match:
        differences.append(f"toc_found: expected {exp_finder.get('toc_found')}, got {actual_finder.get('toc_found')}")

    # Compare page range
    exp_range = exp_finder.get("toc_page_range", {})
    act_range = actual_finder.get("toc_page_range", {})

    page_range_match = (
        exp_range.get("start_page") == act_range.get("start_page") and
        exp_range.get("end_page") == act_range.get("end_page")
    )
    if not page_range_match:
        differences.append(
            f"page_range: expected {exp_range.get('start_page')}-{exp_range.get('end_page')}, "
            f"got {act_range.get('start_page')}-{act_range.get('end_page')}"
        )

    matches = toc_found_match and page_range_match

    return FindPhaseComparison(
        matches=matches,
        toc_found_match=toc_found_match,
        page_range_match=page_range_match,
        expected_range=exp_range,
        actual_range=act_range,
        differences=differences,
    )


def compare_extract_phase(expected: ExpectedExtractTocResult, actual_toc: Dict[str, Any]) -> ExtractPhaseComparison:
    """Compare extract phase output to expected."""
    # Handle both old format (nested under 'toc') and new format (flat)
    expected_toc = expected.toc.get("toc", expected.toc)
    actual_toc_data = actual_toc.get("toc", actual_toc)

    expected_entries = expected_toc.get("entries", [])
    actual_entries = actual_toc_data.get("entries", [])

    differences = []
    mismatched_entries = []

    # Compare entry counts
    entry_count_match = len(expected_entries) == len(actual_entries)
    if not entry_count_match:
        differences.append(
            f"entry_count: expected {len(expected_entries)}, got {len(actual_entries)}"
        )

    # Compare entries
    title_matches = 0
    perfect_matches = 0

    for i, exp_entry in enumerate(expected_entries):
        if i >= len(actual_entries):
            mismatched_entries.append({
                "index": i,
                "reason": "missing",
                "expected": exp_entry,
                "actual": None,
            })
            continue

        act_entry = actual_entries[i]

        # Check if entries match (case-insensitive, normalized for title)
        exp_title = normalize_text((exp_entry.get("title") or "").lower())
        act_title = normalize_text((act_entry.get("title") or "").lower())

        # Note: level_name excluded from accuracy - it's informational only
        entry_matches = (
            exp_entry.get("entry_number") == act_entry.get("entry_number") and
            exp_title == act_title and
            exp_entry.get("level") == act_entry.get("level") and
            exp_entry.get("printed_page_number") == act_entry.get("printed_page_number")
        )

        if entry_matches:
            perfect_matches += 1
        else:
            mismatched_entries.append({
                "index": i,
                "expected": exp_entry,
                "actual": act_entry,
            })

        # Track title matches separately (more lenient, case-insensitive, normalized)
        if exp_title == act_title:
            title_matches += 1

    # Check for extra entries in actual
    if len(actual_entries) > len(expected_entries):
        for i in range(len(expected_entries), len(actual_entries)):
            mismatched_entries.append({
                "index": i,
                "reason": "extra",
                "expected": None,
                "actual": actual_entries[i],
            })

    title_match_rate = title_matches / len(expected_entries) if expected_entries else 1.0
    entry_match_rate = perfect_matches / len(expected_entries) if expected_entries else 1.0

    perfect_entry_match = len(mismatched_entries) == 0 and entry_count_match
    matches = perfect_entry_match

    return ExtractPhaseComparison(
        matches=matches,
        entry_count_match=entry_count_match,
        perfect_entry_match=perfect_entry_match,
        expected_count=len(expected_entries),
        actual_count=len(actual_entries),
        title_match_rate=title_match_rate,
        entry_match_rate=entry_match_rate,
        mismatched_entries=mismatched_entries,
        differences=differences,
    )


def compare_book(book_id: str) -> BookComparison:
    """Compare a book's extract-toc output against expected results."""
    try:
        # Load expected
        expected = load_expected_result(book_id)

        # Load actual from library
        storage = BookStorage(book_id)
        stage_storage = storage.stage("extract-toc")

        # Check if outputs exist
        finder_path = stage_storage.output_dir / "finder_result.json"
        toc_path = stage_storage.output_dir / "toc.json"

        if not finder_path.exists():
            return BookComparison(
                book_id=book_id,
                success=False,
                error="finder_result.json not found - stage not run?"
            )

        if not toc_path.exists():
            return BookComparison(
                book_id=book_id,
                success=False,
                error="toc.json not found - extraction not complete?"
            )

        # Load actual results
        actual_finder = stage_storage.load_file("finder_result.json")
        actual_toc = stage_storage.load_file("toc.json")

        # Compare
        find_comparison = compare_find_phase(expected, actual_finder)
        extract_comparison = compare_extract_phase(expected, actual_toc)

        success = find_comparison.matches and extract_comparison.matches

        return BookComparison(
            book_id=book_id,
            success=success,
            find_phase=find_comparison,
            extract_phase=extract_comparison,
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

    print(f"\nOVERALL: {'✅ PASS' if result.success else '❌ FAIL'}")

    # Find phase
    if result.find_phase:
        fp = result.find_phase
        print(f"\nFIND PHASE: {'✅' if fp.matches else '❌'}")
        print(f"  ToC Found: {'✅' if fp.toc_found_match else '❌'}")
        print(f"  Page Range: {'✅' if fp.page_range_match else '❌'}")
        if not fp.page_range_match:
            print(f"    Expected: {fp.expected_range.get('start_page')}-{fp.expected_range.get('end_page')}")
            if fp.actual_range:
                print(f"    Actual:   {fp.actual_range.get('start_page')}-{fp.actual_range.get('end_page')}")

    # Extract phase
    if result.extract_phase:
        ep = result.extract_phase
        print(f"\nEXTRACT PHASE: {'✅' if ep.matches else '❌'}")
        print(f"  Entry Count: {'✅' if ep.entry_count_match else '❌'} ({ep.actual_count} vs {ep.expected_count} expected)")
        print(f"  Perfect Match: {'✅' if ep.perfect_entry_match else '❌'}")
        print(f"  Title Match Rate: {ep.title_match_rate*100:.1f}%")
        print(f"  Entry Match Rate: {ep.entry_match_rate*100:.1f}%")

        if ep.mismatched_entries and (verbose or len(ep.mismatched_entries) <= 10):
            print(f"\n  Mismatched Entries ({len(ep.mismatched_entries)}):")
            print_mismatched_entries(ep.mismatched_entries, verbose)
        elif ep.mismatched_entries:
            print(f"\n  Mismatched Entries: {len(ep.mismatched_entries)} (use --verbose to see details)")
            # Show summary by category
            print_mismatch_summary(ep.mismatched_entries)


def print_mismatched_entries(mismatches: List[Dict], verbose: bool):
    """Print mismatched entries."""
    for m in mismatches[:20] if not verbose else mismatches:
        idx = m['index']
        exp = m.get('expected')
        act = m.get('actual')
        reason = m.get('reason')

        if reason == 'missing':
            print(f"    #{idx}: MISSING - expected '{exp.get('title')}'")
        elif reason == 'extra':
            print(f"    #{idx}: EXTRA - got '{act.get('title')}'")
        else:
            # Show differences
            diffs = []
            if exp.get('entry_number') != act.get('entry_number'):
                diffs.append(f"num: {exp.get('entry_number')}→{act.get('entry_number')}")
            exp_title_norm = normalize_text((exp.get('title') or '').lower())
            act_title_norm = normalize_text((act.get('title') or '').lower())
            if exp_title_norm != act_title_norm:
                diffs.append(f"title: '{exp.get('title')}'→'{act.get('title')}'")
            if exp.get('level') != act.get('level'):
                diffs.append(f"level: {exp.get('level')}→{act.get('level')}")
            if exp.get('printed_page_number') != act.get('printed_page_number'):
                diffs.append(f"page: {exp.get('printed_page_number')}→{act.get('printed_page_number')}")

            print(f"    #{idx}: {'; '.join(diffs)}")

    if len(mismatches) > 20 and not verbose:
        print(f"    ... and {len(mismatches) - 20} more")


def print_mismatch_summary(mismatches: List[Dict]):
    """Print summary of mismatches by category."""
    issues = {
        'entry_number': 0,
        'title': 0,
        'level': 0,
        'page': 0,
        'missing': 0,
        'extra': 0,
    }

    for m in mismatches:
        reason = m.get('reason')
        if reason == 'missing':
            issues['missing'] += 1
        elif reason == 'extra':
            issues['extra'] += 1
        else:
            exp = m['expected']
            act = m['actual']
            if exp.get('entry_number') != act.get('entry_number'):
                issues['entry_number'] += 1
            exp_title_norm = normalize_text((exp.get('title') or '').lower())
            act_title_norm = normalize_text((act.get('title') or '').lower())
            if exp_title_norm != act_title_norm:
                issues['title'] += 1
            if exp.get('level') != act.get('level'):
                issues['level'] += 1
            if exp.get('printed_page_number') != act.get('printed_page_number'):
                issues['page'] += 1

    summary_parts = [f"{k}: {v}" for k, v in issues.items() if v > 0]
    print(f"    Summary: {', '.join(summary_parts)}")


def compare_all_books(failures_only: bool = False, verbose: bool = False):
    """Compare all books with expected results."""
    book_ids = list_books()

    print(f"\n{'='*70}")
    print(f"EXTRACT-TOC ACCURACY COMPARISON")
    print(f"Comparing {len(book_ids)} books against expected results")
    print(f"{'='*70}")

    results = []
    for book_id in book_ids:
        result = compare_book(book_id)
        results.append(result)

        # Print progress
        status = "✅" if result.success else "❌"
        if result.extract_phase:
            rate = f"{result.extract_phase.entry_match_rate*100:.0f}%"
        else:
            rate = "N/A"
        print(f"  {status} {book_id}: {rate}")

    # Summary
    total = len(results)
    perfect = len([r for r in results if r.success])
    errors = len([r for r in results if r.error])

    print(f"\n{'='*70}")
    print(f"SUMMARY")
    print(f"{'='*70}")
    print(f"  Perfect Match: {perfect}/{total} ({perfect/total*100:.1f}%)")
    print(f"  Errors: {errors}")

    # Calculate average rates
    extract_results = [r.extract_phase for r in results if r.extract_phase]
    if extract_results:
        avg_title = sum(r.title_match_rate for r in extract_results) / len(extract_results)
        avg_entry = sum(r.entry_match_rate for r in extract_results) / len(extract_results)
        print(f"  Avg Title Match: {avg_title*100:.1f}%")
        print(f"  Avg Entry Match: {avg_entry*100:.1f}%")

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
                elif result.extract_phase:
                    ep = result.extract_phase
                    print(f"  ❌ {result.book_id}: {ep.actual_count}/{ep.expected_count} entries, "
                          f"{ep.entry_match_rate*100:.0f}% match")

    print()


def main():
    parser = argparse.ArgumentParser(
        description="Compare extract-toc outputs against expected results",
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
