#!/usr/bin/env python3
"""
Real-time pipeline monitoring tool

Parses structured JSON logs to show:
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
from typing import Dict, List, Optional, Any
from dataclasses import dataclass


@dataclass
class StageStatus:
    """Status for a single pipeline stage."""
    stage: str
    status: str  # 'not_started', 'in_progress', 'completed', 'failed'
    progress_current: int = 0
    progress_total: int = 0
    progress_percent: float = 0.0
    cost_usd: float = 0.0
    model: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    errors: List[Dict[str, Any]] = None
    warnings: List[Dict[str, Any]] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.warnings is None:
            self.warnings = []
        if self.metadata is None:
            self.metadata = {}


class LogParser:
    """Parse JSON log files (.jsonl) for pipeline monitoring."""

    @staticmethod
    def parse_log_file(log_path: Path) -> List[Dict[str, Any]]:
        """Parse a single .jsonl file into list of log entries."""
        entries = []

        if not log_path.exists():
            return entries

        try:
            with open(log_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        # Parse timestamp if present
                        if 'timestamp' in entry:
                            try:
                                entry['timestamp_dt'] = datetime.fromisoformat(entry['timestamp'])
                            except:
                                pass
                        entries.append(entry)
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass

        return entries

    @staticmethod
    def get_stage_logs(logs_dir: Path, stage: str) -> List[Dict[str, Any]]:
        """Get all log entries for a specific stage, sorted by timestamp."""
        all_entries = []

        if not logs_dir.exists():
            return all_entries

        # Find all log files for this stage
        log_files = sorted(logs_dir.glob(f"{stage}_*.jsonl"))

        for log_file in log_files:
            entries = LogParser.parse_log_file(log_file)
            all_entries.extend(entries)

        # Sort by timestamp
        all_entries.sort(key=lambda e: e.get('timestamp', ''))

        return all_entries

    @staticmethod
    def get_latest_progress(logs: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Get the most recent progress event from logs."""
        for entry in reversed(logs):
            if 'progress' in entry:
                return entry
        return None

    @staticmethod
    def get_accumulated_cost(logs: List[Dict[str, Any]]) -> float:
        """Sum all cost_usd fields from logs."""
        total = 0.0
        for entry in logs:
            if 'cost_usd' in entry:
                total += entry['cost_usd']
        return total

    @staticmethod
    def get_stage_duration(logs: List[Dict[str, Any]]) -> Optional[float]:
        """Get duration from completion event, or calculate from timestamps."""
        # Check for explicit duration in completion event
        for entry in reversed(logs):
            if 'duration_seconds' in entry:
                return entry['duration_seconds']

        # Calculate from first/last timestamp
        if logs and 'timestamp_dt' in logs[0] and 'timestamp_dt' in logs[-1]:
            duration = (logs[-1]['timestamp_dt'] - logs[0]['timestamp_dt']).total_seconds()
            return duration if duration > 0 else None

        return None

    @staticmethod
    def get_errors_warnings(logs: List[Dict[str, Any]], limit: int = 5) -> tuple[List[Dict], List[Dict]]:
        """Get recent actionable ERROR entries only.

        Strategy:
        - Only include actual errors that affected output
        - Skip retry warnings (they're noisy and usually succeed)
        - Skip errors that were later resolved by successful retry
        """
        errors = []

        # Track which pages had retry successes
        retry_successes = set()
        for entry in logs:
            msg = entry.get('message', '')
            # Look for "Agent X succeeded on retry" messages
            if 'succeeded on retry' in msg.lower():
                # Extract page number if present
                if '[page' in msg:
                    try:
                        page_str = msg.split('[page')[1].split(']')[0].strip()
                        retry_successes.add(page_str)
                    except:
                        pass

        # Collect only unresolved errors
        for entry in reversed(logs):
            if entry.get('level') == 'ERROR' and len(errors) < limit:
                msg = entry.get('message', '')

                # Check if this error was later resolved
                is_resolved = False
                if '[page' in msg:
                    try:
                        page_str = msg.split('[page')[1].split(']')[0].strip()
                        if page_str in retry_successes:
                            is_resolved = True
                    except:
                        pass

                # Only include unresolved errors
                if not is_resolved:
                    errors.append(entry)

            if len(errors) >= limit:
                break

        # Don't return warnings - they're too noisy (retries are normal)
        return errors, []

    @staticmethod
    def is_stage_complete(logs: List[Dict[str, Any]]) -> bool:
        """Check if stage has completion event."""
        for entry in reversed(logs):
            if 'Completed' in entry.get('message', '') or 'Complete' in entry.get('message', ''):
                return True
        return False

    @staticmethod
    def get_start_time(logs: List[Dict[str, Any]]) -> Optional[datetime]:
        """Get stage start time."""
        if logs and 'timestamp_dt' in logs[0]:
            return logs[0]['timestamp_dt']
        return None

    @staticmethod
    def get_end_time(logs: List[Dict[str, Any]]) -> Optional[datetime]:
        """Get stage end time if completed."""
        if LogParser.is_stage_complete(logs) and logs and 'timestamp_dt' in logs[-1]:
            return logs[-1]['timestamp_dt']
        return None


class PipelineMonitor:
    """Monitor pipeline progress in real-time using JSON logs."""

    def __init__(self, scan_id: str, storage_root: Path = None):
        self.scan_id = scan_id
        self.storage_root = storage_root or Path.home() / "Documents" / "book_scans"
        self.book_dir = self.storage_root / scan_id

        # Verify book exists
        if not self.book_dir.exists():
            raise ValueError(f"Book directory not found: {self.book_dir}")

        self.logs_dir = self.book_dir / "logs"

        # Load metadata for total pages
        metadata_file = self.book_dir / "metadata.json"
        if metadata_file.exists():
            with open(metadata_file) as f:
                self.metadata = json.load(f)
        else:
            self.metadata = {}

        # Get total pages from metadata, or infer from OCR directory
        # Check both 'total_pages' and 'total_pages_processed' for compatibility
        self.total_pages = self.metadata.get('total_pages', 0) or self.metadata.get('total_pages_processed', 0)
        if self.total_pages == 0:
            ocr_dir = self.book_dir / "ocr"
            if ocr_dir.exists():
                self.total_pages = len(list(ocr_dir.glob("page_*.json")))

    def get_stage_status(self, stage: str) -> StageStatus:
        """Get status for a specific stage using hybrid checkpoint + file-based approach.

        Strategy:
        - Completion status (completed vs in_progress): From checkpoint (authoritative)
        - Progress percentage: Count actual files on disk (real-time for in-progress stages)
        - Cost & timing: From checkpoint (accurate tracking)
        """
        from checkpoint import CheckpointManager
        from datetime import datetime
        import os

        # Initialize checkpoint manager for this stage
        checkpoint = CheckpointManager(
            scan_id=self.scan_id,
            stage=stage,
            storage_root=self.storage_root
        )

        # Get checkpoint status (authoritative for completion)
        checkpoint_state = checkpoint.get_status()
        status = checkpoint_state.get('status', 'not_started')

        # If checkpoint says "not_started" but has completed pages, it's actually in_progress
        # (This handles stages that don't explicitly mark themselves as in_progress)
        if status == 'not_started':
            completed_pages = checkpoint_state.get('completed_pages', [])
            if len(completed_pages) > 0:
                status = 'in_progress'

        # Also check for recent log activity (for stages that don't update checkpoints during processing)
        if status == 'not_started' and self.logs_dir.exists():
            import time
            import glob as glob_module

            # Check for recent log files for this stage
            log_pattern = str(self.logs_dir / f"{stage}_*.jsonl")
            log_files = glob_module.glob(log_pattern)

            if log_files:
                # Check if any log file was modified in the last 5 minutes
                now = time.time()
                for log_file in log_files:
                    try:
                        mtime = os.path.getmtime(log_file)
                        age_seconds = now - mtime
                        if age_seconds < 300:  # 5 minutes
                            status = 'in_progress'
                            break
                    except:
                        pass

        # Extract cost, duration, and model from checkpoint metadata (single source of truth)
        metadata = checkpoint_state.get('metadata', {})
        cost_usd = metadata.get('total_cost_usd', 0.0)
        duration = metadata.get('accumulated_duration_seconds', None)
        model = metadata.get('model', None)

        # If no accumulated duration, fall back to timestamp calculation (backwards compatibility)
        if duration is None:
            start_time = None
            end_time = None

            if checkpoint_state.get('created_at'):
                try:
                    start_time = datetime.fromisoformat(checkpoint_state['created_at'])
                except:
                    pass

            if checkpoint_state.get('completed_at'):
                try:
                    end_time = datetime.fromisoformat(checkpoint_state['completed_at'])
                    if start_time and end_time:
                        duration = (end_time - start_time).total_seconds()
                except:
                    pass

        # Still parse timestamps for display purposes (even though we use accumulated duration)
        start_time = None
        end_time = None
        if checkpoint_state.get('created_at'):
            try:
                start_time = datetime.fromisoformat(checkpoint_state['created_at'])
            except:
                pass
        if checkpoint_state.get('completed_at'):
            try:
                end_time = datetime.fromisoformat(checkpoint_state['completed_at'])
            except:
                pass

        # For progress: Use real-time file counting (especially for in-progress stages)
        progress_current = 0
        progress_total = 0
        progress_percent = 0.0

        # Determine output directory based on stage
        if stage == 'ocr':
            output_dir = self.book_dir / 'ocr'
            pattern = 'page_*.json'
        elif stage == 'correction':
            output_dir = self.book_dir / 'corrected'
            pattern = 'page_*.json'
        elif stage == 'fix':
            output_dir = self.book_dir / 'corrected'
            pattern = 'page_*.json'
        elif stage == 'extract':
            output_dir = self.book_dir / 'structured' / 'extraction'
            pattern = 'batch_*.json'  # Track batch files
        elif stage == 'assemble':
            output_dir = self.book_dir / 'structured'
            pattern = None  # Will check for final outputs
        else:
            output_dir = None
            pattern = None

        # Count actual completed files on disk
        if output_dir and output_dir.exists():
            if pattern:
                completed_files = list(output_dir.glob(pattern))
                progress_current = len(completed_files)
            elif stage == 'extract':
                # For extract, check extraction metadata for total batches
                metadata_file = output_dir / 'metadata.json'
                if metadata_file.exists():
                    try:
                        import json
                        with open(metadata_file) as f:
                            metadata = json.load(f)
                            progress_total = metadata.get('total_batches', 0)
                    except:
                        pass
            elif stage == 'assemble':
                # For assemble, check if final outputs exist
                if (output_dir / 'archive' / 'full_book.md').exists():
                    progress_current = 1
                    progress_total = 1
                    progress_percent = 100.0

        # Get total pages from checkpoint or metadata
        if progress_total == 0:
            # For extract stage, look for total_batches in checkpoint metadata
            if stage == 'extract':
                total_batches = metadata.get('total_batches', 0)
                completed_batches = metadata.get('completed_batches', 0)
                if total_batches > 0:
                    progress_total = total_batches
                    # Use checkpoint's completed_batches if available (more accurate than file count)
                    if completed_batches > 0:
                        progress_current = completed_batches

            # First try checkpoint
            if progress_total == 0:
                progress_total = checkpoint_state.get('total_pages', 0)

            # If not in checkpoint, try metadata.json
            if progress_total == 0:
                metadata_file = self.book_dir / 'metadata.json'
                if metadata_file.exists():
                    try:
                        import json
                        with open(metadata_file) as f:
                            metadata = json.load(f)
                            progress_total = metadata.get('total_pages_processed', 0)
                    except:
                        pass

            # Last resort: count PDF pages
            if progress_total == 0:
                source_dir = self.book_dir / 'source'
                if source_dir.exists():
                    try:
                        from PyPDF2 import PdfReader
                        for pdf_file in source_dir.glob('*.pdf'):
                            try:
                                reader = PdfReader(str(pdf_file))
                                progress_total += len(reader.pages)
                            except:
                                pass
                    except ImportError:
                        pass

        # Calculate percentage
        if progress_total > 0 and stage != 'structure':
            progress_percent = (progress_current / progress_total) * 100

        # Get logs for errors/warnings (only if stage is not complete)
        # Completed stages shouldn't show stale errors
        errors = []
        warnings = []
        if status != 'completed':
            logs = LogParser.get_stage_logs(self.logs_dir, stage)
            errors, warnings = LogParser.get_errors_warnings(logs, limit=5)

        return StageStatus(
            stage=stage,
            status=status,  # From checkpoint (authoritative)
            progress_current=progress_current,  # From disk (real-time)
            progress_total=progress_total,
            progress_percent=progress_percent,
            cost_usd=cost_usd,  # From checkpoint (accurate)
            model=model,  # From checkpoint
            start_time=start_time,  # From checkpoint
            end_time=end_time,  # From checkpoint
            duration_seconds=duration,  # From checkpoint
            errors=errors,
            warnings=warnings,
            metadata=metadata  # Pass through checkpoint metadata
        )

    def get_all_stages_status(self) -> Dict[str, StageStatus]:
        """Get status for all pipeline stages."""
        # Separate extract/assemble instead of combined structure
        stages = ['ocr', 'correction', 'fix', 'extract', 'assemble']
        return {stage: self.get_stage_status(stage) for stage in stages}

    def calculate_eta(self, stage_status: StageStatus) -> Optional[str]:
        """Calculate ETA for in-progress stage."""
        if stage_status.status != 'in_progress':
            return None

        if not stage_status.start_time or stage_status.progress_current == 0:
            return None

        # Calculate rate from elapsed time
        # Strip timezone info to avoid offset-naive vs offset-aware comparison errors
        start_time_naive = stage_status.start_time.replace(tzinfo=None)
        elapsed = (datetime.now() - start_time_naive).total_seconds()
        if elapsed < 1:
            return None

        pages_per_second = stage_status.progress_current / elapsed
        remaining = stage_status.progress_total - stage_status.progress_current

        if pages_per_second <= 0 or remaining <= 0:
            return None

        remaining_seconds = remaining / pages_per_second

        # Format as duration
        if remaining_seconds < 60:
            return f"{int(remaining_seconds)}s"
        elif remaining_seconds < 3600:
            mins = int(remaining_seconds / 60)
            secs = int(remaining_seconds % 60)
            return f"{mins}m {secs}s"
        else:
            hours = int(remaining_seconds / 3600)
            mins = int((remaining_seconds % 3600) / 60)
            return f"{hours}h {mins}m"

    def format_duration(self, seconds: Optional[float]) -> str:
        """Format duration in seconds to human-readable format."""
        if seconds is None or seconds < 0:
            return "N/A"

        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            mins = int(seconds / 60)
            secs = int(seconds % 60)
            return f"{mins}m {secs}s"
        else:
            hours = int(seconds / 3600)
            mins = int((seconds % 3600) / 60)
            return f"{hours}h {mins}m"

    def print_status(self, clear_screen: bool = False):
        """Print current status from JSON logs."""
        if clear_screen:
            print("\033[2J\033[H", end="")  # Clear screen and move cursor to top

        print("=" * 70)
        print(f"📊 Pipeline Monitor: {self.scan_id}")
        print(f"   Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70)
        print()

        # Get all stages status
        stages_status = self.get_all_stages_status()

        # Display each stage
        total_cost = 0.0
        total_duration = 0.0

        for stage_name, stage_status in stages_status.items():
            total_cost += stage_status.cost_usd
            if stage_status.duration_seconds:
                total_duration += stage_status.duration_seconds

            # Choose icon
            if stage_status.status == 'completed':
                icon = "✅"
            elif stage_status.status == 'in_progress':
                icon = "⏳"
            else:
                icon = "○"

            # Format stage name (consistent width)
            display_name = stage_name.capitalize()[:10].ljust(10)

            # Build status line with consistent spacing
            if stage_status.status == 'not_started':
                status_line = f"{icon} {display_name} Not started"
            elif stage_status.status == 'completed':
                # Format duration (right-aligned in 8 chars: "9m 39s")
                duration_str = self.format_duration(stage_status.duration_seconds)
                duration_str = duration_str.rjust(8)

                # Format cost (right-aligned with 2 decimals)
                cost_str = f"${stage_status.cost_usd:6.2f}" if stage_status.cost_usd > 0 else " " * 7

                # Format model (short form)
                model_str = ""
                if stage_status.model:
                    # Extract short model name (e.g., "gpt-4o-mini" from "openai/gpt-4o-mini")
                    model_short = stage_status.model.split('/')[-1] if '/' in stage_status.model else stage_status.model
                    model_str = f" [{model_short}]"

                status_line = f"{icon} {display_name} Complete ({duration_str}) - {cost_str}{model_str}"

                # Add failure count for extract stage if any batches failed
                if stage_name == 'extract':
                    failed_batches = stage_status.metadata.get('failed_batches', 0)
                    if failed_batches > 0:
                        status_line += f" - ⚠️ {failed_batches} failed"
            else:  # in_progress
                if stage_status.progress_total > 0:
                    status_line = f"{icon} {display_name} {stage_status.progress_current}/{stage_status.progress_total} ({stage_status.progress_percent:.1f}%)"

                    # Add ETA
                    eta = self.calculate_eta(stage_status)
                    if eta:
                        status_line += f" - ETA: {eta}"

                    # Add failure indicator if applicable (for extract stage)
                    if stage_name == 'extract':
                        failed_batches = stage_status.metadata.get('failed_batches', 0)
                        if failed_batches > 0:
                            status_line += f" - ⚠️ {failed_batches} failed"

                    # Add cost if present
                    if stage_status.cost_usd > 0:
                        status_line += f" - ${stage_status.cost_usd:.2f}"
                else:
                    status_line = f"{icon} {display_name} In progress..."

            print(status_line)

        print()

        # Total cost and time
        if total_cost > 0:
            print(f"💰 Total Cost: ${total_cost:.2f}")
        if total_duration > 0:
            duration_formatted = self.format_duration(total_duration)
            print(f"⏱️  Total Time: {duration_formatted}")
        if total_cost > 0 or total_duration > 0:
            print()

        print("=" * 70)


def monitor_pipeline(scan_id: str, refresh_interval: int = 5):
    """Monitor pipeline with automatic refresh."""
    monitor = PipelineMonitor(scan_id)

    print(f"Monitoring {scan_id}...")
    print(f"Press Ctrl+C to exit")
    print()

    try:
        while True:
            monitor.print_status(clear_screen=True)
            time.sleep(refresh_interval)
    except KeyboardInterrupt:
        print("\n\nMonitoring stopped.")


def print_status(scan_id: str):
    """Print status once (no refresh)."""
    monitor = PipelineMonitor(scan_id)
    monitor.print_status(clear_screen=False)


def main():
    """Main entry point for standalone usage."""
    if len(sys.argv) < 2:
        print("Usage: python tools/monitor.py <scan-id> [refresh-interval]")
        print("Example: python tools/monitor.py modest-lovelace 5")
        sys.exit(1)

    scan_id = sys.argv[1]
    refresh_interval = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    monitor_pipeline(scan_id, refresh_interval)


if __name__ == "__main__":
    main()
