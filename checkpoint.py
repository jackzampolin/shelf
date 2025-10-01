#!/usr/bin/env python3
"""
Checkpoint system for reliable pipeline restarts

Provides:
- File-based checkpointing with atomic writes
- Thread-safe progress tracking
- Resume from last successful state
- Cost tracking and savings estimates
- Validation of existing outputs

Usage:
    from checkpoint import CheckpointManager

    checkpoint = CheckpointManager(scan_id="modest-lovelace", stage="correction")

    # Get pages to process (skips completed if resuming)
    pages_to_process = checkpoint.get_remaining_pages(
        total_pages=447,
        resume=True
    )

    # Mark page completed (thread-safe)
    checkpoint.mark_completed(page_num=42, cost_usd=0.02)

    # Complete stage
    checkpoint.mark_stage_complete()
"""

import json
import threading
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict, Any, Set


class CheckpointManager:
    """
    Manage pipeline checkpoints for resumable processing.

    Thread-safe checkpoint manager that tracks completed pages,
    costs, and progress. Supports atomic updates and validation.
    """

    CHECKPOINT_VERSION = "1.0"

    def __init__(
        self,
        scan_id: str,
        stage: str,
        storage_root: Optional[Path] = None,
        output_dir: Optional[str] = None,
        file_pattern: str = "page_{:04d}.json"
    ):
        """
        Initialize checkpoint manager.

        Args:
            scan_id: Scan identifier (e.g., "modest-lovelace")
            stage: Pipeline stage (e.g., "ocr", "correction", "fix", "structure")
            storage_root: Base directory (default: ~/Documents/book_scans)
            output_dir: Output directory name for validation (auto-detected if None)
            file_pattern: Output file pattern (default: page_{:04d}.json)
        """
        self.scan_id = scan_id
        self.stage = stage
        self.storage_root = storage_root or Path.home() / "Documents" / "book_scans"
        self.book_dir = self.storage_root / scan_id

        # Checkpoint directory and file
        self.checkpoint_dir = self.book_dir / "checkpoints"
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_file = self.checkpoint_dir / f"{stage}.json"

        # Output validation settings
        self.output_dir = output_dir or self._detect_output_dir(stage)
        self.file_pattern = file_pattern

        # Thread-safe state
        self._lock = threading.Lock()
        self._state = self._load_or_create_checkpoint()

    def _detect_output_dir(self, stage: str) -> str:
        """Auto-detect output directory based on stage."""
        mapping = {
            "ocr": "ocr",
            "correction": "corrected",
            "fix": "corrected",  # Fix updates corrected files
            "structure": "structured"
        }
        return mapping.get(stage, stage)

    def _load_or_create_checkpoint(self) -> Dict[str, Any]:
        """Load existing checkpoint or create new one."""
        if self.checkpoint_file.exists():
            try:
                with open(self.checkpoint_file, 'r') as f:
                    state = json.load(f)

                # Validate version compatibility
                if state.get('version') != self.CHECKPOINT_VERSION:
                    # Version mismatch - start fresh
                    return self._create_new_checkpoint()

                return state
            except Exception:
                # Corrupted checkpoint - start fresh
                return self._create_new_checkpoint()
        else:
            return self._create_new_checkpoint()

    def _create_new_checkpoint(self) -> Dict[str, Any]:
        """Create a new checkpoint state."""
        return {
            "version": self.CHECKPOINT_VERSION,
            "scan_id": self.scan_id,
            "stage": self.stage,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "status": "not_started",
            "completed_pages": [],
            "total_pages": 0,
            "progress": {
                "completed": 0,
                "remaining": 0,
                "percent": 0.0
            },
            "costs": {
                "total_usd": 0.0
            },
            "metadata": {},
            "validation": {
                "output_dir": self.output_dir,
                "file_pattern": self.file_pattern
            }
        }

    def _save_checkpoint(self):
        """Save checkpoint with atomic write (must be called with lock held)."""
        # Update timestamp
        self._state['updated_at'] = datetime.now().isoformat()

        # Write to temp file first
        temp_file = self.checkpoint_file.with_suffix('.json.tmp')
        with open(temp_file, 'w') as f:
            json.dump(self._state, f, indent=2)

        # Atomic rename
        temp_file.replace(self.checkpoint_file)

    def validate_page_output(self, page_num: int) -> bool:
        """
        Validate that output file exists and is valid.

        Args:
            page_num: Page number to validate

        Returns:
            True if page output is valid, False otherwise
        """
        output_path = self.book_dir / self.output_dir / self.file_pattern.format(page_num)

        if not output_path.exists():
            return False

        # Validate JSON is parseable
        try:
            with open(output_path, 'r') as f:
                data = json.load(f)
            # Basic sanity check - file should have some content
            return len(data) > 0
        except Exception:
            return False

    def scan_existing_outputs(self, total_pages: int) -> Set[int]:
        """
        Scan output directory for valid completed pages.

        Args:
            total_pages: Total number of pages expected

        Returns:
            Set of page numbers with valid output files
        """
        valid_pages = set()

        output_dir_path = self.book_dir / self.output_dir
        if not output_dir_path.exists():
            return valid_pages

        for page_num in range(1, total_pages + 1):
            if self.validate_page_output(page_num):
                valid_pages.add(page_num)

        return valid_pages

    def get_remaining_pages(
        self,
        total_pages: int,
        resume: bool = True,
        start_page: int = 1,
        end_page: Optional[int] = None
    ) -> List[int]:
        """
        Get list of pages that need processing.

        Args:
            total_pages: Total pages in book
            resume: If True, skip already-completed pages
            start_page: First page to consider (default: 1)
            end_page: Last page to consider (default: total_pages)

        Returns:
            List of page numbers to process
        """
        if end_page is None:
            end_page = total_pages

        with self._lock:
            self._state['total_pages'] = total_pages

            if not resume:
                # Start fresh - process all pages in range
                pages = list(range(start_page, end_page + 1))
                self._state['status'] = 'in_progress'
                self._save_checkpoint()
                return pages

            # Resume mode - check what's already done
            # First, sync checkpoint with actual output files
            valid_outputs = self.scan_existing_outputs(total_pages)

            # Update checkpoint with validated pages
            self._state['completed_pages'] = sorted(list(valid_outputs))

            # Calculate remaining pages in requested range
            completed_set = set(self._state['completed_pages'])
            remaining_pages = [
                p for p in range(start_page, end_page + 1)
                if p not in completed_set
            ]

            # Update progress
            self._state['progress'] = {
                "completed": len(completed_set),
                "remaining": len(remaining_pages),
                "percent": (len(completed_set) / total_pages * 100) if total_pages > 0 else 0
            }

            self._state['status'] = 'in_progress'
            self._save_checkpoint()

            return remaining_pages

    def mark_completed(self, page_num: int, cost_usd: float = 0.0):
        """
        Mark a page as completed (thread-safe).

        Args:
            page_num: Page number that was completed
            cost_usd: Cost of processing this page
        """
        with self._lock:
            # Add to completed list if not already there
            if page_num not in self._state['completed_pages']:
                self._state['completed_pages'].append(page_num)
                self._state['completed_pages'].sort()

            # Update costs
            self._state['costs']['total_usd'] += cost_usd

            # Update progress
            total = self._state.get('total_pages', 0)
            completed = len(self._state['completed_pages'])
            self._state['progress'] = {
                "completed": completed,
                "remaining": max(0, total - completed),
                "percent": (completed / total * 100) if total > 0 else 0
            }

            # Save checkpoint every 10 pages or if significant cost
            if completed % 10 == 0 or cost_usd > 0.5:
                self._save_checkpoint()

    def mark_stage_complete(self, metadata: Optional[Dict[str, Any]] = None):
        """
        Mark stage as complete.

        Args:
            metadata: Optional metadata to store with completion
        """
        with self._lock:
            self._state['status'] = 'completed'
            self._state['completed_at'] = datetime.now().isoformat()

            if metadata:
                self._state['metadata'].update(metadata)

            self._save_checkpoint()

    def mark_stage_failed(self, error: str):
        """
        Mark stage as failed.

        Args:
            error: Error message
        """
        with self._lock:
            self._state['status'] = 'failed'
            self._state['error'] = error
            self._state['failed_at'] = datetime.now().isoformat()
            self._save_checkpoint()

    def reset(self):
        """Reset checkpoint to initial state."""
        with self._lock:
            self._state = self._create_new_checkpoint()
            self._save_checkpoint()

    def get_status(self) -> Dict[str, Any]:
        """
        Get current checkpoint status (thread-safe copy).

        Returns:
            Dict containing checkpoint state
        """
        with self._lock:
            return self._state.copy()

    def estimate_cost_saved(self, avg_cost_per_page: float = 0.02) -> float:
        """
        Estimate cost saved by resuming.

        Args:
            avg_cost_per_page: Average cost per page (default: $0.02)

        Returns:
            Estimated cost saved in USD
        """
        with self._lock:
            completed = len(self._state['completed_pages'])
            return completed * avg_cost_per_page

    def get_progress_summary(self) -> str:
        """
        Get human-readable progress summary.

        Returns:
            Progress summary string
        """
        with self._lock:
            progress = self._state['progress']
            status = self._state['status']

            if status == 'completed':
                return f"✅ Stage completed - {progress['completed']} pages"
            elif status == 'in_progress':
                return (
                    f"⏳ In progress - {progress['completed']}/{self._state['total_pages']} "
                    f"({progress['percent']:.1f}%) - {progress['remaining']} remaining"
                )
            elif status == 'failed':
                return f"❌ Failed - {progress['completed']} pages completed before failure"
            else:
                return "○ Not started"


# Context manager for convenient checkpoint usage
class checkpoint_scope:
    """
    Context manager for checkpoint operations.

    Usage:
        with checkpoint_scope(scan_id, stage) as checkpoint:
            pages = checkpoint.get_remaining_pages(447, resume=True)
            for page in pages:
                process_page(page)
                checkpoint.mark_completed(page, cost=0.02)
    """

    def __init__(self, scan_id: str, stage: str, **kwargs):
        self.checkpoint = CheckpointManager(scan_id, stage, **kwargs)

    def __enter__(self):
        return self.checkpoint

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            # Normal exit - mark as complete
            self.checkpoint.mark_stage_complete()
        else:
            # Exception occurred - mark as failed
            self.checkpoint.mark_stage_failed(str(exc_val))
        return False
