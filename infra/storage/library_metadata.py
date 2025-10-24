"""
Library metadata for operational state.

This file manages library-level state that doesn't belong in individual book metadata:
- Shuffle orders for regenerate-stage commands
- Future: batch processing queues, library-wide settings, etc.

Philosophy: Book metadata lives in metadata.json per book (filesystem-based).
           Operational state lives in .library.json (session/workflow state).
"""

import json
import threading
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime
from infra.config import Config


class LibraryMetadata:
    """
    Manage library-level operational state.

    Stores state that spans multiple books or workflow sessions:
    - Shuffle orders for stage regeneration (persistent random order)
    - Future: processing queues, library settings, etc.

    Thread-safe for concurrent operations.
    """

    METADATA_VERSION = "1.0"
    METADATA_FILENAME = ".library.json"

    def __init__(self, storage_root: Optional[Path] = None):
        """
        Initialize library metadata.

        Args:
            storage_root: Path to library root (defaults to Config.book_storage_root)
        """
        self.storage_root = storage_root or Config.book_storage_root
        self.metadata_file = self.storage_root / self.METADATA_FILENAME

        # Thread-safe state
        self._lock = threading.Lock()
        self._state = self._load_or_create_metadata()

    def _load_or_create_metadata(self) -> Dict[str, Any]:
        """Load existing metadata or create new one."""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, 'r') as f:
                    state = json.load(f)

                # Validate version
                if state.get('version') != self.METADATA_VERSION:
                    # Version mismatch - start fresh
                    return self._create_new_metadata()

                # Ensure shuffles dict exists
                if 'shuffles' not in state:
                    state['shuffles'] = {}

                return state
            except Exception:
                # Corrupted metadata - start fresh
                return self._create_new_metadata()
        else:
            return self._create_new_metadata()

    def _create_new_metadata(self) -> Dict[str, Any]:
        """Create new metadata state."""
        return {
            "version": self.METADATA_VERSION,
            "shuffles": {}
        }

    def _save(self):
        """Save metadata to disk (atomic write)."""
        import tempfile
        import os

        # Ensure directory exists
        self.metadata_file.parent.mkdir(parents=True, exist_ok=True)

        # Write to temp file first (atomic)
        fd, temp_path = tempfile.mkstemp(
            dir=self.metadata_file.parent,
            prefix=f"{self.METADATA_FILENAME}.tmp"
        )

        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(self._state, f, indent=2)

            # Atomic rename
            os.replace(temp_path, self.metadata_file)
        except Exception:
            # Clean up temp file on error
            try:
                os.unlink(temp_path)
            except Exception:
                pass
            raise

    def get_shuffle(self, stage: str) -> Optional[List[str]]:
        """
        Get shuffle order for a stage.

        Args:
            stage: Stage name (e.g., "labels", "corrected")

        Returns:
            List of scan_ids in shuffle order, or None if no shuffle exists
        """
        with self._lock:
            shuffle_data = self._state['shuffles'].get(stage)
            if not shuffle_data:
                return None
            return shuffle_data.get('order', [])

    def set_shuffle(self, stage: str, scan_ids: List[str]):
        """
        Set shuffle order for a stage.

        Args:
            stage: Stage name (e.g., "labels", "corrected")
            scan_ids: List of scan_ids in desired order
        """
        with self._lock:
            self._state['shuffles'][stage] = {
                'created_at': datetime.now().isoformat(),
                'order': scan_ids
            }
            self._save()

    def clear_shuffle(self, stage: str):
        """
        Clear shuffle order for a stage.

        Args:
            stage: Stage name to clear
        """
        with self._lock:
            if stage in self._state['shuffles']:
                del self._state['shuffles'][stage]
                self._save()

    def list_shuffles(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all shuffle orders.

        Returns:
            Dict mapping stage names to shuffle data
        """
        with self._lock:
            return {
                stage: {
                    'created_at': data.get('created_at'),
                    'count': len(data.get('order', []))
                }
                for stage, data in self._state['shuffles'].items()
            }
