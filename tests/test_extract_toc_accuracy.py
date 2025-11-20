"""
Integration test: Run extract-toc on ground truth and measure accuracy.

This test COSTS MONEY - it runs actual LLM calls on all 19 books.

Usage:
    pytest tests/test_extract_toc_accuracy.py -v -s

The -s flag is important to see the detailed report output.
"""

import pytest
import shutil
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from infra.pipeline.storage.book_storage import BookStorage
from pipeline.extract_toc import ExtractTocStage
from tests.fixtures.toc_ground_truth import load_all_books, GroundTruthBook


@dataclass
class FindPhaseComparison:
    """Comparison result for find phase."""
    book_id: str
    matches: bool

    toc_found_match: bool
    page_range_match: bool
    structure_summary_match: bool

    expected_page_range: Dict[str, int]
    actual_page_range: Optional[Dict[str, int]]

    differences: List[str] = field(default_factory=list)


@dataclass
class FinalizePhaseComparison:
    """Comparison result for finalize phase."""
    book_id: str
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
class BookTestResult:
    """Complete test result for one book."""
    book_id: str
    success: bool

    find_comparison: Optional[FindPhaseComparison]
    finalize_comparison: Optional[FinalizePhaseComparison]

    error: Optional[str] = None


def compare_find_phase(book: GroundTruthBook, actual: Dict[str, Any]) -> FindPhaseComparison:
    """Compare find phase output to expected."""
    expected = book.expected_finder_result
    differences = []

    # Compare toc_found
    toc_found_match = expected.get("toc_found") == actual.get("toc_found")
    if not toc_found_match:
        differences.append(f"toc_found: expected {expected.get('toc_found')}, got {actual.get('toc_found')}")

    # Compare page range
    exp_range = expected.get("toc_page_range", {})
    act_range = actual.get("toc_page_range", {})

    page_range_match = (
        exp_range.get("start_page") == act_range.get("start_page") and
        exp_range.get("end_page") == act_range.get("end_page")
    )
    if not page_range_match:
        differences.append(
            f"page_range: expected {exp_range.get('start_page')}-{exp_range.get('end_page')}, "
            f"got {act_range.get('start_page')}-{act_range.get('end_page')}"
        )

    # Compare structure summary (basic check)
    exp_structure = expected.get("structure_summary", {})
    act_structure = actual.get("structure_summary", {})

    structure_summary_match = (
        exp_structure.get("total_levels") == act_structure.get("total_levels")
    )
    if not structure_summary_match:
        differences.append(
            f"total_levels: expected {exp_structure.get('total_levels')}, "
            f"got {act_structure.get('total_levels')}"
        )

    matches = toc_found_match and page_range_match and structure_summary_match

    return FindPhaseComparison(
        book_id=book.scan_id,
        matches=matches,
        toc_found_match=toc_found_match,
        page_range_match=page_range_match,
        structure_summary_match=structure_summary_match,
        expected_page_range=exp_range,
        actual_page_range=act_range,
        differences=differences,
    )


def compare_finalize_phase(book: GroundTruthBook, actual: Dict[str, Any]) -> FinalizePhaseComparison:
    """Compare finalize phase output to expected."""
    expected_toc = book.expected_toc.get("toc", book.expected_toc)
    actual_toc = actual.get("toc", actual)

    expected_entries = expected_toc.get("entries", [])
    actual_entries = actual_toc.get("entries", [])

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

        # Check if entries match (case-insensitive for title)
        exp_title = (exp_entry.get("title") or "").lower()
        act_title = (act_entry.get("title") or "").lower()

        entry_matches = (
            exp_entry.get("entry_number") == act_entry.get("entry_number") and
            exp_title == act_title and
            exp_entry.get("level") == act_entry.get("level") and
            exp_entry.get("level_name") == act_entry.get("level_name") and
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

        # Track title matches separately (more lenient, case-insensitive)
        if exp_title == act_title:
            title_matches += 1

    title_match_rate = title_matches / len(expected_entries) if expected_entries else 1.0
    entry_match_rate = perfect_matches / len(expected_entries) if expected_entries else 1.0

    perfect_entry_match = len(mismatched_entries) == 0 and entry_count_match
    matches = perfect_entry_match

    return FinalizePhaseComparison(
        book_id=book.scan_id,
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


def run_extract_toc_and_compare(book: GroundTruthBook) -> BookTestResult:
    """Run extract-toc on a ground truth book and compare results."""
    try:
        # Setup: Point to ground truth directory
        storage = BookStorage(
            book.scan_id,
            storage_root=Path("tests/fixtures/toc_ground_truth")
        )

        # Clean any existing extract-toc output
        extract_dir = storage.stage("extract-toc").output_dir
        if extract_dir.exists():
            shutil.rmtree(extract_dir)

        # Run extract-toc stage
        stage = ExtractTocStage(storage)
        stage.run()

        # Load actual outputs
        actual_finder = storage.stage("extract-toc").load_file("finder_result.json")
        actual_toc = storage.stage("extract-toc").load_file("toc.json")

        # Compare
        find_comparison = compare_find_phase(book, actual_finder)
        finalize_comparison = compare_finalize_phase(book, actual_toc)

        success = find_comparison.matches and finalize_comparison.matches

        return BookTestResult(
            book_id=book.scan_id,
            success=success,
            find_comparison=find_comparison,
            finalize_comparison=finalize_comparison,
        )

    except Exception as e:
        return BookTestResult(
            book_id=book.scan_id,
            success=False,
            find_comparison=None,
            finalize_comparison=None,
            error=str(e),
        )


def generate_report(results: List[BookTestResult]) -> str:
    """Generate comprehensive report from test results."""
    lines = []
    lines.append("\n" + "="*80)
    lines.append("EXTRACT-TOC GROUND TRUTH TEST REPORT")
    lines.append("="*80)

    # Overall statistics
    total = len(results)
    perfect = len([r for r in results if r.success])
    errors = len([r for r in results if r.error])
    partial = total - perfect - errors

    lines.append(f"\nOVERALL ACCURACY:")
    lines.append(f"  Books Tested: {total}")
    lines.append(f"  Perfect Match: {perfect} ({perfect/total*100:.1f}%)")
    lines.append(f"  Partial Match: {partial} ({partial/total*100:.1f}%)")
    lines.append(f"  Errors: {errors} ({errors/total*100:.1f}%)")

    # Phase-specific accuracy
    find_results = [r.find_comparison for r in results if r.find_comparison]
    finalize_results = [r.finalize_comparison for r in results if r.finalize_comparison]

    if find_results:
        toc_found_matches = len([f for f in find_results if f.toc_found_match])
        page_range_matches = len([f for f in find_results if f.page_range_match])
        structure_matches = len([f for f in find_results if f.structure_summary_match])

        lines.append(f"\nFIND PHASE ACCURACY:")
        lines.append(f"  ToC Found: {toc_found_matches}/{len(find_results)} ({toc_found_matches/len(find_results)*100:.1f}%)")
        lines.append(f"  Page Range Exact: {page_range_matches}/{len(find_results)} ({page_range_matches/len(find_results)*100:.1f}%)")
        lines.append(f"  Structure Summary: {structure_matches}/{len(find_results)} ({structure_matches/len(find_results)*100:.1f}%)")

    if finalize_results:
        entry_count_matches = len([f for f in finalize_results if f.entry_count_match])
        perfect_entries = len([f for f in finalize_results if f.perfect_entry_match])
        avg_title_match = sum(f.title_match_rate for f in finalize_results) / len(finalize_results)
        avg_entry_match = sum(f.entry_match_rate for f in finalize_results) / len(finalize_results)

        lines.append(f"\nFINALIZE PHASE ACCURACY:")
        lines.append(f"  Entry Count Match: {entry_count_matches}/{len(finalize_results)} ({entry_count_matches/len(finalize_results)*100:.1f}%)")
        lines.append(f"  Perfect Entry Match: {perfect_entries}/{len(finalize_results)} ({perfect_entries/len(finalize_results)*100:.1f}%)")
        lines.append(f"  Avg Title Match Rate: {avg_title_match*100:.1f}%")
        lines.append(f"  Avg Entry Match Rate: {avg_entry_match*100:.1f}%")

    # Per-book details
    lines.append(f"\nPER-BOOK RESULTS:")
    lines.append("-" * 80)

    for result in sorted(results, key=lambda r: (not r.success, r.book_id)):
        if result.success:
            lines.append(f"  ✅ {result.book_id}: Perfect match")
        elif result.error:
            lines.append(f"  ❌ {result.book_id}: ERROR")
            lines.append(f"     {result.error}")
        else:
            lines.append(f"  ⚠️  {result.book_id}: Partial match")

            if result.find_comparison and not result.find_comparison.matches:
                lines.append(f"     Find phase issues:")
                for diff in result.find_comparison.differences:
                    lines.append(f"       - {diff}")

            if result.finalize_comparison and not result.finalize_comparison.matches:
                lines.append(f"     Finalize phase issues:")
                for diff in result.finalize_comparison.differences:
                    lines.append(f"       - {diff}")

                # Show first few mismatched entries
                mismatches = result.finalize_comparison.mismatched_entries[:3]
                if mismatches:
                    lines.append(f"     Entry mismatches (showing first {len(mismatches)}):")
                    for m in mismatches:
                        lines.append(f"       Entry {m['index']}:")
                        exp = m['expected']
                        act = m.get('actual')
                        if act:
                            if exp.get('title') != act.get('title'):
                                lines.append(f"         title: '{exp.get('title')}' → '{act.get('title')}'")
                            if exp.get('level') != act.get('level'):
                                lines.append(f"         level: {exp.get('level')} → {act.get('level')}")
                            if exp.get('printed_page_number') != act.get('printed_page_number'):
                                lines.append(f"         page: {exp.get('printed_page_number')} → {act.get('printed_page_number')}")
                        else:
                            lines.append(f"         MISSING in actual output")

    lines.append("\n" + "="*80)

    return "\n".join(lines)


def test_extract_toc_full_library():
    """
    Run extract-toc on all ground truth books and measure accuracy.

    WARNING: This test costs money! It runs actual LLM calls on all 19 books.

    The test will:
    1. Run extract-toc on each book
    2. Compare outputs to expected results
    3. Generate comprehensive report
    4. Fail if any book doesn't match perfectly

    Use this to measure prompt improvements over time.
    """
    books = load_all_books()

    print(f"\n{'='*80}")
    print(f"Running extract-toc on {len(books)} books...")
    print(f"WARNING: This will cost money (LLM calls)")
    print(f"{'='*80}\n")

    results = []

    for i, book in enumerate(books, 1):
        print(f"[{i}/{len(books)}] Testing {book.scan_id}...", end=" ", flush=True)

        result = run_extract_toc_and_compare(book)
        results.append(result)

        if result.success:
            print("✅")
        elif result.error:
            print(f"❌ ERROR")
        else:
            print("⚠️  PARTIAL")

    # Generate and print report
    report = generate_report(results)
    print(report)

    # Fail if any books had issues
    failed = [r for r in results if not r.success]
    if failed:
        pytest.fail(f"\n{len(failed)}/{len(results)} books did not match perfectly. See report above.")
