#!/usr/bin/env python3
"""
Compare extract-toc test runs to track accuracy improvements over time.

Usage:
    # Compare latest run with previous run
    python tests/extract_toc/compare_accuracy.py

    # Compare two specific runs
    python tests/extract_toc/compare_accuracy.py 20250102_143022_a1b2c3d 20250102_151030_b2c3d4e

    # Show details for specific book
    python tests/extract_toc/compare_accuracy.py --book accidental-president

    # List all runs
    python tests/extract_toc/compare_accuracy.py --list
"""

import sys
import argparse
from pathlib import Path
from typing import Optional, List
import json

from tests.test_results_manager import ResultsManager


def list_runs(manager: ResultsManager):
    """List all test runs with summary stats."""
    runs_dir = manager.test_dir / "runs"
    if not runs_dir.exists():
        print("No test runs found.")
        return

    runs = sorted(runs_dir.iterdir(), key=lambda p: p.name, reverse=True)
    if not runs:
        print("No test runs found.")
        return

    print(f"\n{'='*80}")
    print(f"TEST RUNS FOR: {manager.test_name}")
    print(f"{'='*80}\n")

    for run_dir in runs:
        summary_file = run_dir / "summary.json"
        if not summary_file.exists():
            continue

        with open(summary_file) as f:
            summary = json.load(f)

        stats = summary["stats"]
        git = summary["git"]

        timestamp = summary["timestamp"][:19]  # Remove milliseconds
        commit = git["commit_short"]
        branch = git["branch"]
        dirty = "⚠️ dirty" if git["is_dirty"] else ""

        perfect = stats["perfect_match"]
        total = stats["total_books"]
        pct = stats["perfect_match_pct"]

        print(f"{run_dir.name}")
        print(f"  {timestamp}  |  {commit} ({branch}) {dirty}")
        print(f"  Accuracy: {perfect}/{total} perfect ({pct:.1f}%)  |  "
              f"Title: {stats['avg_title_match']:.1f}%  |  "
              f"Entry: {stats['avg_entry_match']:.1f}%")
        print()


def show_book_details(manager: ResultsManager, book_id: str, run_name: Optional[str] = None):
    """Show detailed results for a specific book."""
    if run_name:
        run_dir = manager.runs_dir / run_name
        if not run_dir.exists():
            print(f"Run not found: {run_name}")
            return
    else:
        # Use latest run
        latest_link = manager.test_dir / "latest"
        if not latest_link.exists():
            print("No test runs found.")
            return
        run_dir = latest_link.resolve()

    book_file = run_dir / "books" / f"{book_id}.json"
    if not book_file.exists():
        print(f"Book not found in this run: {book_id}")
        return

    with open(book_file) as f:
        result = json.load(f)

    # Load summary for context
    with open(run_dir / "summary.json") as f:
        summary = json.load(f)

    print(f"\n{'='*80}")
    print(f"BOOK: {book_id}")
    print(f"{'='*80}")
    print(f"\nRun: {run_dir.name}")
    print(f"Timestamp: {summary['timestamp'][:19]}")
    print(f"Git: {summary['git']['commit_short']} ({summary['git']['branch']})")

    print(f"\nOVERALL: {'✅ PASS' if result['success'] else '❌ FAIL'}")

    if result.get("error"):
        print(f"\nERROR: {result['error']}")
        return

    # Find phase
    if result.get("find_phase"):
        fp = result["find_phase"]
        print(f"\nFIND PHASE: {'✅' if fp['matches'] else '❌'}")
        print(f"  ToC Found: {'✅' if fp['toc_found_match'] else '❌'}")
        print(f"  Page Range: {'✅' if fp['page_range_match'] else '❌'}")
        print(f"    Expected: {fp['expected_page_range'].get('start_page')}-{fp['expected_page_range'].get('end_page')}")
        if fp['actual_page_range']:
            print(f"    Actual:   {fp['actual_page_range'].get('start_page')}-{fp['actual_page_range'].get('end_page')}")
        print(f"  Structure: {'✅' if fp['structure_summary_match'] else '❌'}")

        if fp['differences']:
            print(f"\n  Differences:")
            for diff in fp['differences']:
                print(f"    - {diff}")

    # Finalize phase
    if result.get("finalize_phase"):
        fp = result["finalize_phase"]
        print(f"\nFINALIZE PHASE: {'✅' if fp['matches'] else '❌'}")
        print(f"  Entry Count: {'✅' if fp['entry_count_match'] else '❌'} "
              f"({fp['actual_count']} vs {fp['expected_count']} expected)")
        print(f"  Perfect Match: {'✅' if fp['perfect_entry_match'] else '❌'}")
        print(f"  Title Match Rate: {fp['title_match_rate']*100:.1f}%")
        print(f"  Entry Match Rate: {fp['entry_match_rate']*100:.1f}%")

        if fp['differences']:
            print(f"\n  Differences:")
            for diff in fp['differences']:
                print(f"    - {diff}")

        # Show mismatched entries
        if fp['mismatched_entries']:
            print(f"\n  Mismatched Entries ({len(fp['mismatched_entries'])} total):")

            # Categorize issues
            issues = {
                'entry_number': [],
                'title_exact': [],
                'title_case': [],
                'level': [],
                'level_name': [],
                'page': [],
                'missing': []
            }

            for m in fp['mismatched_entries']:
                idx = m['index']
                exp = m['expected']
                act = m.get('actual')

                if not act:
                    issues['missing'].append(idx)
                    continue

                # Check each field
                if exp.get('entry_number') != act.get('entry_number'):
                    issues['entry_number'].append(f"#{idx}: {exp.get('entry_number')}→{act.get('entry_number')}")

                exp_title = exp.get('title') or ''
                act_title = act.get('title') or ''
                if exp_title != act_title:
                    if exp_title.lower() == act_title.lower():
                        issues['title_case'].append(f"#{idx}: case difference")
                    else:
                        issues['title_exact'].append(f"#{idx}: '{exp_title}' → '{act_title}'")

                if exp.get('level') != act.get('level'):
                    issues['level'].append(f"#{idx}: L{exp.get('level')}→L{act.get('level')}")

                if exp.get('level_name') != act.get('level_name'):
                    issues['level_name'].append(f"#{idx}: {exp.get('level_name')}→{act.get('level_name')}")

                if exp.get('printed_page_number') != act.get('printed_page_number'):
                    issues['page'].append(f"#{idx}: {exp.get('printed_page_number')}→{act.get('printed_page_number')}")

            # Print by category
            for issue_type, items in issues.items():
                if items:
                    print(f"\n    {issue_type.replace('_', ' ').title()}:")
                    for item in items[:15]:  # Show first 15
                        print(f"      {item}")
                    if len(items) > 15:
                        print(f"      ... and {len(items) - 15} more")

    print(f"\n{'='*80}\n")


def compare_two_runs(manager: ResultsManager, run1_name: Optional[str], run2_name: Optional[str]):
    """Compare two test runs."""
    # Get runs
    if run1_name:
        run1_dir = manager.runs_dir / run1_name
        if not run1_dir.exists():
            print(f"Run not found: {run1_name}")
            return
    else:
        # Get second-latest run
        runs = sorted(manager.runs_dir.iterdir(), key=lambda p: p.name, reverse=True)
        if len(runs) < 2:
            print("Need at least 2 test runs to compare.")
            return
        run1_dir = runs[1]

    if run2_name:
        run2_dir = manager.runs_dir / run2_name
        if not run2_dir.exists():
            print(f"Run not found: {run2_name}")
            return
    else:
        # Get latest run
        latest_link = manager.test_dir / "latest"
        if not latest_link.exists():
            print("No test runs found.")
            return
        run2_dir = latest_link.resolve()

    # Load summaries
    with open(run1_dir / "summary.json") as f:
        summary1 = json.load(f)

    with open(run2_dir / "summary.json") as f:
        summary2 = json.load(f)

    # Print comparison
    print(f"\n{'='*80}")
    print(f"COMPARING TEST RUNS")
    print(f"{'='*80}\n")

    print(f"BEFORE: {run1_dir.name}")
    print(f"  Timestamp: {summary1['timestamp'][:19]}")
    print(f"  Git: {summary1['git']['commit_short']} ({summary1['git']['branch']})")
    print()

    print(f"AFTER:  {run2_dir.name}")
    print(f"  Timestamp: {summary2['timestamp'][:19]}")
    print(f"  Git: {summary2['git']['commit_short']} ({summary2['git']['branch']})")

    # Overall stats comparison
    stats1 = summary1["stats"]
    stats2 = summary2["stats"]

    print(f"\nOVERALL ACCURACY:")
    print(f"  Perfect Match:")
    print(f"    Before: {stats1['perfect_match']}/{stats1['total_books']} ({stats1['perfect_match_pct']:.1f}%)")
    print(f"    After:  {stats2['perfect_match']}/{stats2['total_books']} ({stats2['perfect_match_pct']:.1f}%)")
    delta = stats2['perfect_match'] - stats1['perfect_match']
    print(f"    Delta:  {'+' if delta >= 0 else ''}{delta}")

    print(f"\n  Average Title Match Rate:")
    print(f"    Before: {stats1['avg_title_match']:.1f}%")
    print(f"    After:  {stats2['avg_title_match']:.1f}%")
    delta = stats2['avg_title_match'] - stats1['avg_title_match']
    print(f"    Delta:  {'+' if delta >= 0 else ''}{delta:.1f}%")

    print(f"\n  Average Entry Match Rate:")
    print(f"    Before: {stats1['avg_entry_match']:.1f}%")
    print(f"    After:  {stats2['avg_entry_match']:.1f}%")
    delta = stats2['avg_entry_match'] - stats1['avg_entry_match']
    print(f"    Delta:  {'+' if delta >= 0 else ''}{delta:.1f}%")

    # Per-book changes
    books1 = {r["book_id"]: r for r in summary1["book_results"]}
    books2 = {r["book_id"]: r for r in summary2["book_results"]}

    improved = []
    regressed = []

    for book_id in sorted(set(books1.keys()) | set(books2.keys())):
        result1 = books1.get(book_id)
        result2 = books2.get(book_id)

        if result1 and result2:
            # Check for status changes
            if not result1["success"] and result2["success"]:
                improved.append(book_id)
            elif result1["success"] and not result2["success"]:
                regressed.append(book_id)

    if improved or regressed:
        print(f"\nPER-BOOK CHANGES:")
        if improved:
            print(f"\n  Improved ({len(improved)}):")
            for book_id in improved:
                print(f"    ✅ {book_id}")

        if regressed:
            print(f"\n  Regressed ({len(regressed)}):")
            for book_id in regressed:
                print(f"    ❌ {book_id}")

                # Show what changed
                result2 = books2[book_id]
                if result2.get("error"):
                    print(f"       Error: {result2['error']}")
                else:
                    issues = []
                    if not result2.get("find_matches"):
                        issues.append("find phase")
                    if not result2.get("finalize_matches"):
                        issues.append("finalize phase")
                    if issues:
                        print(f"       Issues in: {', '.join(issues)}")
    else:
        print(f"\n  No per-book changes")

    print(f"\n{'='*80}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Compare extract-toc test runs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        "run1",
        nargs="?",
        help="First run name (default: second-latest)"
    )
    parser.add_argument(
        "run2",
        nargs="?",
        help="Second run name (default: latest)"
    )
    parser.add_argument(
        "--book",
        help="Show detailed results for a specific book"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all test runs"
    )
    parser.add_argument(
        "--test-name",
        default="extract-toc",
        help="Test name (default: extract-toc)"
    )

    args = parser.parse_args()

    manager = ResultsManager(test_name=args.test_name)

    if args.list:
        list_runs(manager)
    elif args.book:
        show_book_details(manager, args.book, args.run1)
    else:
        compare_two_runs(manager, args.run1, args.run2)


if __name__ == "__main__":
    main()
