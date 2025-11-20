#!/usr/bin/env python3
"""
Save test results with git metadata for historical tracking.

Usage:
    pytest tests/test_extract_toc_accuracy.py -v -s | tee >(python tests/save_test_results.py)

Or manually:
    python tests/save_test_results.py < test_output.txt
"""

import sys
import json
from pathlib import Path
from datetime import datetime
import subprocess


def get_git_metadata():
    """Get current git commit info."""
    try:
        commit_hash = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL
        ).decode().strip()

        commit_short = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL
        ).decode().strip()

        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL
        ).decode().strip()

        # Get changed files (staged + unstaged)
        changed_files = subprocess.check_output(
            ["git", "diff", "--name-only", "HEAD"],
            stderr=subprocess.DEVNULL
        ).decode().strip().split('\n')
        changed_files = [f for f in changed_files if f]  # Remove empty

        # Get commit message
        commit_msg = subprocess.check_output(
            ["git", "log", "-1", "--pretty=%B"],
            stderr=subprocess.DEVNULL
        ).decode().strip()

        # Check if working directory is dirty
        is_dirty = bool(changed_files)

        return {
            "commit_hash": commit_hash,
            "commit_short": commit_short,
            "branch": branch,
            "commit_message": commit_msg,
            "changed_files": changed_files,
            "is_dirty": is_dirty
        }
    except subprocess.CalledProcessError:
        return {
            "commit_hash": "unknown",
            "commit_short": "unknown",
            "branch": "unknown",
            "commit_message": "",
            "changed_files": [],
            "is_dirty": False
        }


def extract_summary_stats(output_text):
    """Extract key statistics from test output."""
    stats = {}

    # Look for overall accuracy section
    lines = output_text.split('\n')
    in_overall = False
    in_find = False
    in_finalize = False

    for line in lines:
        if "OVERALL ACCURACY:" in line:
            in_overall = True
            continue
        elif "FIND PHASE ACCURACY:" in line:
            in_overall = False
            in_find = True
            continue
        elif "FINALIZE PHASE ACCURACY:" in line:
            in_find = False
            in_finalize = True
            continue
        elif "PER-BOOK RESULTS:" in line:
            in_finalize = False
            continue

        # Extract stats
        if in_overall:
            if "Books Tested:" in line:
                stats["total_books"] = int(line.split(':')[1].strip())
            elif "Perfect Match:" in line:
                parts = line.split(':')[1].strip().split()
                stats["perfect_match"] = int(parts[0].split('/')[0])
                stats["perfect_match_pct"] = float(parts[1].strip('()%'))
            elif "Partial Match:" in line:
                parts = line.split(':')[1].strip().split()
                stats["partial_match"] = int(parts[0].split('/')[0])
            elif "Errors:" in line:
                parts = line.split(':')[1].strip().split()
                stats["errors"] = int(parts[0].split('/')[0])

        elif in_finalize:
            if "Avg Title Match Rate:" in line:
                stats["avg_title_match"] = float(line.split(':')[1].strip().rstrip('%'))
            elif "Avg Entry Match Rate:" in line:
                stats["avg_entry_match"] = float(line.split(':')[1].strip().rstrip('%'))

    return stats


def save_results(output_text, output_dir=None):
    """Save test results with metadata."""
    if output_dir is None:
        output_dir = Path("test_results")
    else:
        output_dir = Path(output_dir)

    output_dir.mkdir(exist_ok=True)

    # Get git metadata
    git_meta = get_git_metadata()

    # Create timestamp
    timestamp = datetime.now().isoformat()
    timestamp_safe = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Extract statistics
    stats = extract_summary_stats(output_text)

    # Create filename with git hash and timestamp
    filename = f"result_{timestamp_safe}_{git_meta['commit_short']}.txt"

    # Save full output
    output_file = output_dir / filename
    with open(output_file, 'w') as f:
        f.write(output_text)

    # Save metadata JSON
    metadata = {
        "timestamp": timestamp,
        "git": git_meta,
        "stats": stats,
        "output_file": str(output_file)
    }

    metadata_file = output_dir / f"result_{timestamp_safe}_{git_meta['commit_short']}.json"
    with open(metadata_file, 'w') as f:
        json.dump(metadata, f, indent=2)

    # Update latest.json pointer
    latest_file = output_dir / "latest.json"
    with open(latest_file, 'w') as f:
        json.dump(metadata, f, indent=2)

    print(f"\n✅ Results saved:", file=sys.stderr)
    print(f"   Output: {output_file}", file=sys.stderr)
    print(f"   Metadata: {metadata_file}", file=sys.stderr)
    print(f"   Git: {git_meta['commit_short']} ({git_meta['branch']})", file=sys.stderr)
    if git_meta['is_dirty']:
        print(f"   ⚠️  Working directory has uncommitted changes", file=sys.stderr)
    print(f"   Stats: {stats.get('perfect_match', '?')}/{stats.get('total_books', '?')} perfect ({stats.get('perfect_match_pct', '?')}%)", file=sys.stderr)

    return output_file, metadata_file


def main():
    """Read from stdin and save results."""
    # Read all input
    output_text = sys.stdin.read()

    # Echo to stdout (for tee compatibility)
    print(output_text, end='')

    # Check if this looks like test output
    if "EXTRACT-TOC GROUND TRUTH TEST REPORT" in output_text:
        save_results(output_text)
    else:
        print("\n⚠️  Input doesn't look like test results (no report found)", file=sys.stderr)


if __name__ == "__main__":
    main()
