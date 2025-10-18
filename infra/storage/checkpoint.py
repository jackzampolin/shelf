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
    from infra.checkpoint import CheckpointManager

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
            stage: Pipeline stage (e.g., "ocr", "correction")
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

        # Clean up any orphaned temporary checkpoint files from previous crashes
        self._cleanup_temp_files()

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
            "merge": "processed"
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
            "metadata": {},
            "validation": {
                "output_dir": self.output_dir,
                "file_pattern": self.file_pattern
            }
        }

    def _cleanup_temp_files(self):
        """Clean up orphaned temporary checkpoint files from previous crashes."""
        try:
            # Look for temp files matching this stage
            temp_pattern = f"{self.stage}.json.tmp*"
            for temp_file in self.checkpoint_dir.glob(temp_pattern):
                try:
                    temp_file.unlink()
                except Exception:
                    # Best effort cleanup - don't fail if we can't delete
                    pass
        except Exception:
            # If cleanup fails entirely, don't crash - it's not critical
            pass

    def _save_checkpoint(self):
        """Save checkpoint with atomic write (must be called with lock held)."""
        import os

        # Update timestamp
        self._state['updated_at'] = datetime.now().isoformat()

        temp_file = self.checkpoint_file.with_suffix('.json.tmp')

        try:
            # Write to temp file
            with open(temp_file, 'w') as f:
                json.dump(self._state, f, indent=2)
                f.flush()
                os.fsync(f.fileno())  # Force OS to write

            # Validate temp file is valid JSON before replacing
            with open(temp_file, 'r') as f:
                json.load(f)  # Throws if corrupt

            # Atomic rename
            temp_file.replace(self.checkpoint_file)

        except Exception as e:
            # Clean up temp file on failure
            if temp_file.exists():
                temp_file.unlink()
            # Log but don't crash - checkpoint save is best-effort
            import logging
            logging.error(f"Failed to save checkpoint for {self.scan_id}/{self.stage}: {e}")

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

        # Validate JSON is parseable and has expected structure
        try:
            with open(output_path, 'r') as f:
                data = json.load(f)

            # Stage-specific validation
            if self.stage == "ocr":
                # OCR output must have page_number and blocks
                return ('page_number' in data and
                        'blocks' in data and
                        isinstance(data['blocks'], list))

            elif self.stage == "correction":
                # Correction output must have page_number and blocks
                return ('page_number' in data and
                        'blocks' in data and
                        isinstance(data['blocks'], list))

            elif self.stage == "merge":
                # Validate against MergedPageOutput schema
                try:
                    import importlib
                    merge_schemas = importlib.import_module('pipeline.4_merge.schemas')
                    MergedPageOutput = getattr(merge_schemas, 'MergedPageOutput')
                    MergedPageOutput(**data)
                    return True
                except Exception:
                    return False

            else:
                # Fallback for unknown stages - just check non-empty
                return len(data) > 0

        except Exception:
            return False

    def _auto_detect_total_pages(self) -> int:
        """
        Auto-detect total pages by counting source page images.

        Returns:
            Number of source pages, or 0 if source directory doesn't exist
        """
        source_dir = self.book_dir / "source"
        if not source_dir.exists():
            return 0

        # Count page_*.png files
        source_pages = sorted(source_dir.glob("page_*.png"))
        return len(source_pages)

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
        total_pages: Optional[int] = None,
        resume: bool = True,
        start_page: int = 1,
        end_page: Optional[int] = None
    ) -> List[int]:
        """
        Get list of pages that need processing.

        Args:
            total_pages: Total pages in book (auto-detected from source/ if not provided)
            resume: If True, skip already-completed pages
            start_page: First page to consider (default: 1)
            end_page: Last page to consider (default: total_pages)

        Returns:
            List of page numbers to process
        """
        # Auto-detect total_pages if not provided
        if total_pages is None:
            total_pages = self._auto_detect_total_pages()
            if total_pages == 0:
                raise ValueError(
                    f"Could not auto-detect total_pages for {self.scan_id}. "
                    f"Source directory not found or empty. "
                    f"Please provide total_pages explicitly."
                )

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

            # Only set status to "in_progress" if there's work to do
            # Preserve "completed" status if already marked complete
            if len(remaining_pages) > 0:
                self._state['status'] = 'in_progress'
            elif self._state['status'] == 'not_started':
                # All pages complete but never marked complete
                self._state['status'] = 'in_progress'
            # else: preserve existing status (completed, failed, etc.)

            self._save_checkpoint()

            return remaining_pages

    def mark_completed(self, page_num: int, cost_usd: float = 0.0):
        """
        Mark a page as completed (thread-safe).

        Args:
            page_num: Page number that was completed
            cost_usd: Cost for this page in USD (accumulated in metadata)
        """
        with self._lock:
            # Add to completed list if not already there
            is_new_page = page_num not in self._state['completed_pages']

            # Early return if page already completed and no cost to add (avoid redundant saves)
            if not is_new_page and cost_usd == 0:
                return

            if is_new_page:
                self._state['completed_pages'].append(page_num)
                self._state['completed_pages'].sort()

            # Accumulate cost in metadata (ONLY for new pages to avoid double-counting)
            if cost_usd > 0 and is_new_page:
                current_cost = self._state['metadata'].get('total_cost_usd', 0.0)
                self._state['metadata']['total_cost_usd'] = current_cost + cost_usd

            # Update progress
            total = self._state.get('total_pages', 0)
            completed = len(self._state['completed_pages'])
            self._state['progress'] = {
                "completed": completed,
                "remaining": max(0, total - completed),
                "percent": (completed / total * 100) if total > 0 else 0
            }

            # Save checkpoint on every page (disk I/O is negligible vs LLM latency)
            self._save_checkpoint()

    def mark_stage_complete(self, metadata: Optional[Dict[str, Any]] = None):
        """
        Mark stage as complete.

        CRITICAL: This saves any pending checkpoint updates before marking complete.
        This ensures pages completed since the last incremental save are recorded.

        Args:
            metadata: Optional metadata to store with completion
        """
        with self._lock:
            # CRITICAL FIX: Save current state first to capture any pending updates
            # This ensures pages completed since last incremental save are recorded
            self._save_checkpoint()

            # Calculate this run's duration
            current_run_duration = 0.0
            if self._state.get('created_at'):
                try:
                    start_time = datetime.fromisoformat(self._state['created_at'])
                    end_time = datetime.now()
                    current_run_duration = (end_time - start_time).total_seconds()
                except:
                    pass

            # Accumulate duration in metadata (don't rely on created_at/completed_at timestamps)
            existing_duration = self._state.get('metadata', {}).get('accumulated_duration_seconds', 0.0)
            total_duration = existing_duration + current_run_duration

            self._state['status'] = 'completed'
            self._state['completed_at'] = datetime.now().isoformat()

            if metadata:
                self._state['metadata'].update(metadata)

            # Always set accumulated duration
            self._state['metadata']['accumulated_duration_seconds'] = total_duration

            # Save again with completion status
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

    def reset(self, confirm: bool = False):
        """
        Reset checkpoint to initial state.

        Args:
            confirm: If True, prompt for confirmation before resetting if progress exists

        Returns:
            True if reset, False if cancelled by user
        """
        with self._lock:
            # Check if there's existing progress
            if confirm and self.checkpoint_file.exists():
                status = self._state.copy()
                completed = len(status.get('completed_pages', []))
                total = status.get('total_pages', 0)
                cost = status.get('metadata', {}).get('total_cost_usd', 0.0)

                if completed > 0:
                    # Release lock before user input
                    pass  # Will release at end of with block

        # Check needs to be outside lock to avoid deadlock during input()
        if confirm and self.checkpoint_file.exists():
            status = self.get_status()  # Thread-safe copy
            completed = len(status.get('completed_pages', []))
            total = status.get('total_pages', 0)
            cost = status.get('metadata', {}).get('total_cost_usd', 0.0)

            if completed > 0:
                print(f"\n⚠️  Checkpoint exists with progress:")
                print(f"   Pages: {completed}/{total} complete ({completed/total*100:.1f}%)" if total > 0 else f"   Pages: {completed} complete")
                print(f"   Cost: ${cost:.2f}")
                print(f"   This will DELETE progress and start over.")

                response = input("\n   Continue with reset? (type 'yes' to confirm): ").strip().lower()
                if response != 'yes':
                    print("   Cancelled.")
                    return False

        # Perform reset
        with self._lock:
            self._state = self._create_new_checkpoint()
            self._save_checkpoint()
            return True

    def flush(self):
        """
        Force save of current checkpoint state.

        Use this before critical operations or when you want to ensure
        the checkpoint is persisted (e.g., before shutdown).
        """
        with self._lock:
            self._save_checkpoint()

    def get_status(self) -> Dict[str, Any]:
        """
        Get current checkpoint status (thread-safe copy).

        Returns:
            Dict containing checkpoint state
        """
        with self._lock:
            return self._state.copy()

    def estimate_cost_saved(self) -> float:
        """
        Estimate cost saved by resuming based on actual costs if available.

        Returns:
            Estimated cost saved in USD, or 0.0 if no cost data available

        Note:
            Uses actual costs from metadata.total_cost_usd when available.
            Returns 0.0 if no actual cost data exists (honest estimate).
        """
        with self._lock:
            completed_pages = len(self._state['completed_pages'])
            total_pages = self._state.get('total_pages', 0)

            if completed_pages == 0 or total_pages == 0:
                return 0.0

            # Try to use actual cost from metadata
            actual_cost = self._state.get('metadata', {}).get('total_cost_usd', 0.0)

            if actual_cost > 0 and completed_pages > 0:
                # Calculate actual cost per page
                cost_per_page = actual_cost / completed_pages
                return completed_pages * cost_per_page
            else:
                # No actual data - can't provide honest estimate
                return 0.0

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
