#!/usr/bin/env python3
"""
Real-time pipeline monitoring tool

Shows:
- Progress percentage and ETA
- Processing rate (pages/min)
- Cost tracking
- Recent errors and warnings
- Stage status
"""

import sys
import json
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional


class PipelineMonitor:
    """Monitor pipeline progress in real-time."""

    def __init__(self, book_slug: str, storage_root: Path = None):
        self.book_slug = book_slug
        self.storage_root = storage_root or Path.home() / "Documents" / "book_scans"
        self.book_dir = self.storage_root / book_slug

        # Verify book exists
        if not self.book_dir.exists():
            raise ValueError(f"Book directory not found: {self.book_dir}")

        # Load metadata
        metadata_file = self.book_dir / "metadata.json"
        if metadata_file.exists():
            with open(metadata_file) as f:
                self.metadata = json.load(f)
        else:
            self.metadata = {}

        # Get total pages from metadata, or infer from OCR directory
        self.total_pages = self.metadata.get('total_pages', 0)
        if self.total_pages == 0:
            # Try to infer from OCR output
            ocr_dir = self.book_dir / "ocr"
            if ocr_dir.exists():
                self.total_pages = len(list(ocr_dir.glob("page_*.json")))

    def get_stage_progress(self) -> Dict:
        """Get progress for each stage."""
        ocr_dir = self.book_dir / "ocr"
        corrected_dir = self.book_dir / "corrected"
        structured_dir = self.book_dir / "structured"
        needs_review_dir = self.book_dir / "needs_review"

        # Count pages in each stage
        ocr_pages = len(list(ocr_dir.glob("page_*.json"))) if ocr_dir.exists() else 0
        corrected_pages = len(list(corrected_dir.glob("page_*.json"))) if corrected_dir.exists() else 0
        flagged_pages = len(list(needs_review_dir.glob("page_*.json"))) if needs_review_dir.exists() else 0

        # Check structure completion
        structure_complete = (structured_dir / "metadata.json").exists() if structured_dir.exists() else False

        return {
            "ocr": {
                "completed": ocr_pages,
                "total": self.total_pages,
                "percentage": (ocr_pages / self.total_pages * 100) if self.total_pages > 0 else 0
            },
            "correct": {
                "completed": corrected_pages,
                "total": self.total_pages,
                "percentage": (corrected_pages / self.total_pages * 100) if self.total_pages > 0 else 0
            },
            "fix": {
                "flagged": flagged_pages,
                "status": "pending" if flagged_pages > 0 else "none_needed"
            },
            "structure": {
                "status": "complete" if structure_complete else "pending"
            }
        }

    def get_latest_log(self) -> Optional[Path]:
        """Get the most recent pipeline log."""
        logs_dir = self.book_dir / "logs"
        if not logs_dir.exists():
            return None

        log_files = sorted(logs_dir.glob("pipeline_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        return log_files[0] if log_files else None

    def get_latest_report(self) -> Optional[Dict]:
        """Get the most recent pipeline report."""
        logs_dir = self.book_dir / "logs"
        reports_dir = logs_dir / "reports"

        # Check both locations for compatibility
        for dir_path in [reports_dir, logs_dir]:
            if not dir_path.exists():
                continue

            report_files = sorted(dir_path.glob("pipeline_report_*.json"),
                                 key=lambda p: p.stat().st_mtime, reverse=True)
            if report_files:
                with open(report_files[0]) as f:
                    return json.load(f)

        return None

    def get_debug_errors(self, limit: int = 5) -> List[Dict]:
        """Get recent debug error files."""
        debug_dir = self.book_dir / "logs" / "debug"
        errors = []

        # Check new location
        if debug_dir.exists():
            error_files = sorted(debug_dir.glob("page_*_error.txt"),
                                key=lambda p: p.stat().st_mtime, reverse=True)
            for error_file in error_files[:limit]:
                errors.append({
                    "file": error_file.name,
                    "time": datetime.fromtimestamp(error_file.stat().st_mtime),
                    "size": error_file.stat().st_size
                })

        # Also check old location (root) for backwards compatibility
        old_errors = list(self.book_dir.glob("debug_page_*.txt"))
        if old_errors:
            for error_file in sorted(old_errors, key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
                if len(errors) < limit:
                    errors.append({
                        "file": error_file.name,
                        "time": datetime.fromtimestamp(error_file.stat().st_mtime),
                        "size": error_file.stat().st_size,
                        "old_location": True
                    })

        return errors

    def calculate_processing_rate(self, corrected_dir: Path) -> Optional[float]:
        """Calculate pages/minute processing rate."""
        if not corrected_dir.exists():
            return None

        corrected_files = list(corrected_dir.glob("page_*.json"))
        if len(corrected_files) < 2:
            return None

        # Sort by modification time
        sorted_files = sorted(corrected_files, key=lambda p: p.stat().st_mtime)

        # Get time span
        first_time = datetime.fromtimestamp(sorted_files[0].stat().st_mtime)
        last_time = datetime.fromtimestamp(sorted_files[-1].stat().st_mtime)

        duration_minutes = (last_time - first_time).total_seconds() / 60.0

        if duration_minutes < 0.1:  # Less than 6 seconds
            return None

        return len(sorted_files) / duration_minutes

    def estimate_eta(self, completed: int, total: int, rate: Optional[float]) -> Optional[str]:
        """Estimate time to completion."""
        if not rate or rate <= 0 or completed >= total:
            return None

        remaining_pages = total - completed
        remaining_minutes = remaining_pages / rate

        # Format as duration (e.g., "2m 30s" or "1h 15m")
        if remaining_minutes < 1:
            return f"{int(remaining_minutes * 60)}s"
        elif remaining_minutes < 60:
            mins = int(remaining_minutes)
            secs = int((remaining_minutes - mins) * 60)
            return f"{mins}m {secs}s"
        else:
            hours = int(remaining_minutes / 60)
            mins = int(remaining_minutes % 60)
            return f"{hours}h {mins}m"

    def print_status(self, clear_screen: bool = False):
        """Print current status."""
        if clear_screen:
            print("\033[2J\033[H", end="")  # Clear screen and move cursor to top

        print("=" * 70)
        print(f"📊 Pipeline Monitor: {self.book_slug}")
        print(f"   Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70)
        print()

        # Get progress
        progress = self.get_stage_progress()

        # OCR Stage
        ocr = progress['ocr']
        ocr_icon = "✅" if ocr['completed'] >= self.total_pages * 0.95 else "⏳"
        print(f"{ocr_icon} OCR:       {ocr['completed']:3d} / {ocr['total']:3d} pages ({ocr['percentage']:5.1f}%)")

        # Correction Stage
        correct = progress['correct']
        corrected_dir = self.book_dir / "corrected"
        rate = self.calculate_processing_rate(corrected_dir)
        eta = self.estimate_eta(correct['completed'], correct['total'], rate) if rate else None

        correct_icon = "✅" if correct['completed'] >= correct['total'] else "⏳"
        status_line = f"{correct_icon} Correct:   {correct['completed']:3d} / {correct['total']:3d} pages ({correct['percentage']:5.1f}%)"

        if rate:
            status_line += f" - {rate:.1f} pages/min"
        if eta:
            status_line += f" - ETA: {eta}"

        print(status_line)

        # Fix Stage - check if completed from latest report
        fix = progress['fix']
        report = self.get_latest_report()
        fix_completed = False
        fix_cost = None
        if report and 'fix' in report.get('stages', {}):
            fix_stage = report['stages']['fix']
            if fix_stage.get('status') == 'success':
                fix_completed = True
                fix_cost = fix_stage.get('cost_usd', 0)

        if fix_completed:
            fix_icon = "✅"
            fix_status = f"{fix['flagged']} pages fixed"
            if fix_cost:
                fix_status += f" (${fix_cost:.2f})"
        elif fix['status'] == 'none_needed':
            fix_icon = "○"
            fix_status = "None needed"
        else:
            fix_icon = "⏳"
            fix_status = f"{fix['flagged']} pages flagged"

        print(f"{fix_icon} Fix:       {fix_status}")

        # Structure Stage - check for streaming progress in log
        structure = progress['structure']
        structure_tokens = None
        structure_total = 158687  # Approximate from log

        # Try to get latest token count from log
        latest_log = self.get_latest_log()
        if latest_log and latest_log.exists():
            try:
                with open(latest_log) as f:
                    log_content = f.read()
                    # Find last "Tokens: X..." line
                    import re
                    matches = re.findall(r'Tokens: ([\d,]+)', log_content)
                    if matches:
                        structure_tokens = int(matches[-1].replace(',', ''))
            except:
                pass

        if structure['status'] == 'complete':
            structure_icon = "✅"
            structure_status = "Complete"
        elif structure_tokens:
            structure_icon = "⏳"
            pct = (structure_tokens / structure_total * 100)
            structure_status = f"Generating... {structure_tokens:,} / ~{structure_total:,} tokens ({pct:.0f}%)"
        else:
            structure_icon = "⏳"
            structure_status = "Pending"

        print(f"{structure_icon} Structure: {structure_status}")

        print()

        # Latest report
        report = self.get_latest_report()
        if report:
            print("📋 Latest Report:")
            stages = report.get('stages', {})
            for stage_name, stage_data in stages.items():
                status_icon = "✅" if stage_data.get('status') == 'success' else "❌"
                duration = stage_data.get('duration_seconds', 0)
                print(f"   {status_icon} {stage_name}: {duration:.1f}s")

            total_cost = 0
            for stage_name, stage_data in stages.items():
                # Cost tracking would need to be extracted from individual stage stats
                pass

            print()

        # Recent errors
        errors = self.get_debug_errors(limit=3)
        if errors:
            print("⚠️  Recent Debug Files:")
            for error in errors:
                location = " (old location)" if error.get('old_location') else ""
                print(f"   • {error['file']}{location}")
            print()

        # Latest log file
        latest_log = self.get_latest_log()
        if latest_log:
            print(f"📄 Latest Log: {latest_log.name}")
            print()

        print("=" * 70)


def monitor_pipeline(book_slug: str, refresh_interval: int = 5):
    """Monitor pipeline with automatic refresh."""
    monitor = PipelineMonitor(book_slug)

    print(f"Monitoring {book_slug}...")
    print(f"Press Ctrl+C to exit")
    print()

    try:
        while True:
            monitor.print_status(clear_screen=True)
            time.sleep(refresh_interval)
    except KeyboardInterrupt:
        print("\n\nMonitoring stopped.")


def print_status(book_slug: str):
    """Print status once (no refresh)."""
    monitor = PipelineMonitor(book_slug)
    monitor.print_status(clear_screen=False)


def main():
    """Main entry point for standalone usage."""
    if len(sys.argv) < 2:
        print("Usage: python tools/monitor.py <book-slug> [refresh-interval]")
        print("Example: python tools/monitor.py The-Accidental-President 5")
        sys.exit(1)

    book_slug = sys.argv[1]
    refresh_interval = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    monitor_pipeline(book_slug, refresh_interval)


if __name__ == "__main__":
    main()
