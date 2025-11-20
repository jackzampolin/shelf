#!/usr/bin/env python3
"""
Compare two test result runs.

Usage:
    python tests/compare_test_results.py <result1.json> <result2.json>
    python tests/compare_test_results.py --latest --previous
"""

import json
import sys
from pathlib import Path
from datetime import datetime


def load_result(path):
    """Load result metadata."""
    with open(path) as f:
        return json.load(f)


def find_latest_results(n=2):
    """Find the N most recent test results."""
    results_dir = Path("test_results")
    if not results_dir.exists():
        return []

    # Get all metadata files (not latest.json)
    metadata_files = sorted(
        [f for f in results_dir.glob("result_*.json") if f.name != "latest.json"],
        key=lambda f: f.stat().st_mtime,
        reverse=True
    )

    return metadata_files[:n]


def compare_results(result1, result2):
    """Compare two test results and print summary."""
    stats1 = result1.get("stats", {})
    stats2 = result2.get("stats", {})

    git1 = result1.get("git", {})
    git2 = result2.get("git", {})

    print("=" * 80)
    print("TEST RESULTS COMPARISON")
    print("=" * 80)
    print()

    # Git info
    print(f"Run 1: {git1.get('commit_short', '?')} ({git1.get('branch', '?')})")
    if git1.get('commit_message'):
        msg_lines = git1['commit_message'].split('\n')
        print(f"       {msg_lines[0][:60]}")
    print(f"       {result1.get('timestamp', '?')}")
    print()

    print(f"Run 2: {git2.get('commit_short', '?')} ({git2.get('branch', '?')})")
    if git2.get('commit_message'):
        msg_lines = git2['commit_message'].split('\n')
        print(f"       {msg_lines[0][:60]}")
    print(f"       {result2.get('timestamp', '?')}")
    print()

    # Changed files between runs
    if git1.get('changed_files') and git2.get('changed_files'):
        files1 = set(git1.get('changed_files', []))
        files2 = set(git2.get('changed_files', []))
        new_changes = files2 - files1
        if new_changes:
            print(f"Changed files in Run 2:")
            for f in sorted(new_changes):
                print(f"  - {f}")
            print()

    print("-" * 80)
    print()

    # Stats comparison
    metrics = [
        ("Perfect Match", "perfect_match", "perfect_match_pct", "%"),
        ("Partial Match", "partial_match", None, ""),
        ("Errors", "errors", None, ""),
        ("Avg Title Match", "avg_title_match", None, "%"),
        ("Avg Entry Match", "avg_entry_match", None, "%"),
    ]

    print(f"{'Metric':<25} {'Run 1':>12} {'Run 2':>12} {'Change':>12}")
    print("-" * 80)

    for metric_name, key, pct_key, suffix in metrics:
        val1 = stats1.get(key)
        val2 = stats2.get(key)

        if val1 is None or val2 is None:
            continue

        # Format values
        if pct_key:
            pct1 = stats1.get(pct_key, 0)
            pct2 = stats2.get(pct_key, 0)
            str1 = f"{val1} ({pct1:.1f}{suffix})"
            str2 = f"{val2} ({pct2:.1f}{suffix})"
            diff = pct2 - pct1
            diff_str = f"{diff:+.1f}{suffix}"
        else:
            str1 = f"{val1}{suffix}"
            str2 = f"{val2}{suffix}"
            diff = val2 - val1
            diff_str = f"{diff:+d}" if suffix == "" else f"{diff:+.1f}{suffix}"

        # Color code improvements/regressions
        if "Match" in metric_name or metric_name == "Perfect Match":
            # Higher is better
            symbol = "✅" if diff > 0 else "❌" if diff < 0 else "="
        elif metric_name == "Errors":
            # Lower is better
            symbol = "✅" if diff < 0 else "❌" if diff > 0 else "="
        else:
            symbol = ""

        print(f"{metric_name:<25} {str1:>12} {str2:>12} {symbol} {diff_str:>10}")

    print()
    print("=" * 80)

    # Summary
    perfect1 = stats1.get("perfect_match", 0)
    perfect2 = stats2.get("perfect_match", 0)
    total = stats2.get("total_books", stats1.get("total_books", 0))

    if perfect2 > perfect1:
        improvement = perfect2 - perfect1
        rel_improvement = (improvement / perfect1 * 100) if perfect1 > 0 else 0
        print(f"\n✅ IMPROVEMENT: +{improvement} books now perfect ({rel_improvement:.1f}% relative improvement)")
    elif perfect2 < perfect1:
        regression = perfect1 - perfect2
        print(f"\n❌ REGRESSION: -{regression} books now failing")
    else:
        print(f"\n= NO CHANGE in perfect match count")

    # Calculate remaining work
    remaining = total - perfect2
    if remaining > 0:
        print(f"\n📊 Remaining: {remaining} books still need work ({remaining/total*100:.1f}%)")

    print()


def main():
    if len(sys.argv) >= 3:
        if sys.argv[1] == "--latest":
            results = find_latest_results(2)
            if len(results) < 2:
                print("Error: Need at least 2 test results in test_results/", file=sys.stderr)
                sys.exit(1)
            result1_path = results[1]  # Older
            result2_path = results[0]  # Newer
        else:
            result1_path = Path(sys.argv[1])
            result2_path = Path(sys.argv[2])
    else:
        # Auto-find latest 2
        results = find_latest_results(2)
        if len(results) < 2:
            print("Usage: python tests/compare_test_results.py <result1.json> <result2.json>", file=sys.stderr)
            print("   or: python tests/compare_test_results.py --latest", file=sys.stderr)
            print("\nNo recent results found in test_results/", file=sys.stderr)
            sys.exit(1)
        result1_path = results[1]  # Older
        result2_path = results[0]  # Newer

    result1 = load_result(result1_path)
    result2 = load_result(result2_path)

    compare_results(result1, result2)


if __name__ == "__main__":
    main()
