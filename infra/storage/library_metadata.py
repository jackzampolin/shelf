"""
Library metadata for operational state.

This file manages library-level state that doesn't belong in individual book metadata:
- Global shuffle order for all operations (sweeps, webapp listing, etc.)
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
    - Global shuffle order (persistent random order for all operations)
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

                # Ensure shuffle dict exists
                if 'shuffle' not in state:
                    state['shuffle'] = None

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
            "shuffle": None
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

    def get_shuffle(self) -> Optional[List[str]]:
        """
        Get global shuffle order.

        Returns:
            List of scan_ids in shuffle order, or None if no shuffle exists
        """
        with self._lock:
            shuffle_data = self._state.get('shuffle')
            if not shuffle_data:
                return None
            return shuffle_data.get('order', [])

    def set_shuffle(self, scan_ids: List[str]):
        """
        Set global shuffle order.

        Args:
            scan_ids: List of scan_ids in desired order
        """
        with self._lock:
            self._state['shuffle'] = {
                'created_at': datetime.now().isoformat(),
                'order': scan_ids
            }
            self._save()

    def clear_shuffle(self):
        """Clear global shuffle order."""
        with self._lock:
            self._state['shuffle'] = None
            self._save()

    def has_shuffle(self) -> bool:
        """
        Check if global shuffle exists.

        Returns:
            True if shuffle order exists
        """
        with self._lock:
            shuffle_data = self._state.get('shuffle')
            return shuffle_data is not None and len(shuffle_data.get('order', [])) > 0

    def get_shuffle_info(self) -> Optional[Dict[str, Any]]:
        """
        Get shuffle metadata.

        Returns:
            Dict with 'created_at' and 'count' or None if no shuffle
        """
        with self._lock:
            shuffle_data = self._state.get('shuffle')
            if not shuffle_data:
                return None
            return {
                'created_at': shuffle_data.get('created_at'),
                'count': len(shuffle_data.get('order', []))
            }
