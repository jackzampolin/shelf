"""
Test results management for extract-toc accuracy tests.

Provides structured per-book results storage, historical tracking,
and comparison between test runs.
"""

from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
import json
import subprocess
import shutil


class ResultsManager:
    """Manages test results storage and historical tracking."""

    def __init__(self, test_name: str = "extract-toc", results_root: Path = None):
        """
        Initialize results manager.

        Args:
            test_name: Name of the test (used for subdirectory)
            results_root: Root directory for all test results (default: test_results/)
        """
        if results_root is None:
            results_root = Path(__file__).parent.parent / "test_results"

        self.test_name = test_name
        self.results_root = Path(results_root)
        self.test_dir = self.results_root / test_name
        self.runs_dir = self.test_dir / "runs"

        # Create directories
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(exist_ok=True)

    def start_run(self) -> "TestRun":
        """Start a new test run."""
        # Get git metadata
        git_meta = self._get_git_metadata()

        # Create run directory with timestamp and commit hash
        timestamp = datetime.now()
        timestamp_safe = timestamp.strftime("%Y%m%d_%H%M%S")
        commit_short = git_meta["commit_short"]

        run_dir = self.runs_dir / f"{timestamp_safe}_{commit_short}"
        run_dir.mkdir(exist_ok=True)

        # Create books subdirectory
        books_dir = run_dir / "books"
        books_dir.mkdir(exist_ok=True)

        return TestRun(
            run_dir=run_dir,
            timestamp=timestamp,
            git_metadata=git_meta,
            manager=self
        )

    def get_latest_run(self) -> Optional["TestRun"]:
        """Get the most recent test run."""
        runs = sorted(self.runs_dir.iterdir(), key=lambda p: p.name, reverse=True)
        if not runs:
            return None

        # Load summary to reconstruct TestRun
        summary_file = runs[0] / "summary.json"
        if not summary_file.exists():
            return None

        with open(summary_file) as f:
            data = json.load(f)

        return TestRun(
            run_dir=runs[0],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            git_metadata=data["git"],
            manager=self,
            is_loaded=True
        )

    def compare_runs(self, run1: "TestRun", run2: "TestRun") -> Dict[str, Any]:
        """Compare two test runs and return differences."""
        # Load summaries
        summary1 = run1.get_summary()
        summary2 = run2.get_summary()

        # Compare overall stats
        stats_diff = {
            "perfect_match": {
                "before": summary1["stats"]["perfect_match"],
                "after": summary2["stats"]["perfect_match"],
                "delta": summary2["stats"]["perfect_match"] - summary1["stats"]["perfect_match"]
            },
            "avg_title_match": {
                "before": summary1["stats"]["avg_title_match"],
                "after": summary2["stats"]["avg_title_match"],
                "delta": summary2["stats"]["avg_title_match"] - summary1["stats"]["avg_title_match"]
            },
            "avg_entry_match": {
                "before": summary1["stats"]["avg_entry_match"],
                "after": summary2["stats"]["avg_entry_match"],
                "delta": summary2["stats"]["avg_entry_match"] - summary1["stats"]["avg_entry_match"]
            }
        }

        # Find per-book differences
        book_diffs = []
        books1 = {r["book_id"]: r for r in summary1["book_results"]}
        books2 = {r["book_id"]: r for r in summary2["book_results"]}

        for book_id in sorted(set(books1.keys()) | set(books2.keys())):
            result1 = books1.get(book_id)
            result2 = books2.get(book_id)

            if result1 and result2 and result1["success"] != result2["success"]:
                book_diffs.append({
                    "book_id": book_id,
                    "before": "✅ pass" if result1["success"] else "❌ fail",
                    "after": "✅ pass" if result2["success"] else "❌ fail",
                    "status_change": "improved" if result2["success"] else "regressed"
                })

        return {
            "run1": {
                "timestamp": summary1["timestamp"],
                "commit": summary1["git"]["commit_short"],
                "branch": summary1["git"]["branch"]
            },
            "run2": {
                "timestamp": summary2["timestamp"],
                "commit": summary2["git"]["commit_short"],
                "branch": summary2["git"]["branch"]
            },
            "stats": stats_diff,
            "book_changes": book_diffs
        }

    def _get_git_metadata(self) -> Dict[str, Any]:
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
            changed_files = [f for f in changed_files if f]

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


class TestRun:
    """Represents a single test run with multiple book results."""

    def __init__(
        self,
        run_dir: Path,
        timestamp: datetime,
        git_metadata: Dict[str, Any],
        manager: TestResultsManager,
        is_loaded: bool = False
    ):
        self.run_dir = Path(run_dir)
        self.books_dir = self.run_dir / "books"
        self.timestamp = timestamp
        self.git_metadata = git_metadata
        self.manager = manager
        self.is_loaded = is_loaded

        self.book_results: List[Dict[str, Any]] = []

    def add_book_result(self, result: Dict[str, Any]):
        """Add a book result to this run."""
        book_id = result["book_id"]

        # Save individual book result
        book_file = self.books_dir / f"{book_id}.json"
        with open(book_file, 'w') as f:
            json.dump(result, f, indent=2)

        # Track in memory
        self.book_results.append(result)

    def finalize(self) -> Path:
        """
        Finalize the run by saving summary and updating latest symlink.

        Returns:
            Path to summary.json
        """
        # Calculate overall stats
        total = len(self.book_results)
        perfect = len([r for r in self.book_results if r["success"]])
        errors = len([r for r in self.book_results if r.get("error")])
        partial = total - perfect - errors

        # Calculate phase-specific stats
        finalize_results = [
            r["finalize_phase"] for r in self.book_results
            if r.get("finalize_phase")
        ]

        avg_title_match = 0.0
        avg_entry_match = 0.0
        if finalize_results:
            avg_title_match = sum(f["title_match_rate"] for f in finalize_results) / len(finalize_results)
            avg_entry_match = sum(f["entry_match_rate"] for f in finalize_results) / len(finalize_results)

        # Create summary
        summary = {
            "timestamp": self.timestamp.isoformat(),
            "git": self.git_metadata,
            "stats": {
                "total_books": total,
                "perfect_match": perfect,
                "perfect_match_pct": (perfect / total * 100) if total > 0 else 0,
                "partial_match": partial,
                "errors": errors,
                "avg_title_match": avg_title_match * 100,
                "avg_entry_match": avg_entry_match * 100
            },
            "book_results": [
                {
                    "book_id": r["book_id"],
                    "success": r["success"],
                    "error": r.get("error"),
                    "find_matches": r.get("find_phase", {}).get("matches"),
                    "finalize_matches": r.get("finalize_phase", {}).get("matches"),
                    "entry_match_rate": r.get("finalize_phase", {}).get("entry_match_rate", 0) * 100
                }
                for r in sorted(self.book_results, key=lambda x: x["book_id"])
            ]
        }

        # Save summary
        summary_file = self.run_dir / "summary.json"
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)

        # Update latest symlink
        latest_link = self.manager.test_dir / "latest"
        if latest_link.exists() or latest_link.is_symlink():
            latest_link.unlink()
        latest_link.symlink_to(self.run_dir.relative_to(self.manager.test_dir))

        return summary_file

    def get_summary(self) -> Dict[str, Any]:
        """Load and return summary for this run."""
        summary_file = self.run_dir / "summary.json"
        with open(summary_file) as f:
            return json.load(f)

    def get_book_result(self, book_id: str) -> Optional[Dict[str, Any]]:
        """Load and return result for a specific book."""
        book_file = self.books_dir / f"{book_id}.json"
        if not book_file.exists():
            return None

        with open(book_file) as f:
            return json.load(f)

    def get_all_book_results(self) -> List[Dict[str, Any]]:
        """Load all book results for this run."""
        results = []
        for book_file in sorted(self.books_dir.glob("*.json")):
            with open(book_file) as f:
                results.append(json.load(f))
        return results

    def print_summary(self):
        """Print a human-readable summary of this run."""
        summary = self.get_summary()
        stats = summary["stats"]

        print(f"\n{'='*80}")
        print(f"TEST RUN SUMMARY")
        print(f"{'='*80}")
        print(f"\nTimestamp: {summary['timestamp']}")
        print(f"Git: {summary['git']['commit_short']} ({summary['git']['branch']})")
        if summary['git']['is_dirty']:
            print(f"⚠️  Working directory has uncommitted changes")

        print(f"\nOVERALL ACCURACY:")
        print(f"  Books Tested: {stats['total_books']}")
        print(f"  Perfect Match: {stats['perfect_match']} ({stats['perfect_match_pct']:.1f}%)")
        print(f"  Partial Match: {stats['partial_match']}")
        print(f"  Errors: {stats['errors']}")

        print(f"\nFINALIZE PHASE AVERAGES:")
        print(f"  Avg Title Match Rate: {stats['avg_title_match']:.1f}%")
        print(f"  Avg Entry Match Rate: {stats['avg_entry_match']:.1f}%")

        print(f"\nResults saved to: {self.run_dir}")
        print(f"{'='*80}\n")
