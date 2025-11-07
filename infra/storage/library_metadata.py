import json
import threading
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime
from infra.config import Config

class LibraryMetadata:
    METADATA_VERSION = "1.0"
    METADATA_FILENAME = ".library.json"

    def __init__(self, storage_root: Optional[Path] = None):
        self.storage_root = storage_root or Config.book_storage_root
        self.metadata_file = self.storage_root / self.METADATA_FILENAME

        self._lock = threading.Lock()
        self._state = self._load_or_create_metadata()

    def _load_or_create_metadata(self) -> Dict[str, Any]:
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, 'r') as f:
                    state = json.load(f)

                if state.get('version') != self.METADATA_VERSION:
                    return self._create_new_metadata()

                if 'shuffle' not in state:
                    state['shuffle'] = None

                return state
            except Exception:
                return self._create_new_metadata()
        else:
            return self._create_new_metadata()

    def _create_new_metadata(self) -> Dict[str, Any]:
        return {
            "version": self.METADATA_VERSION,
            "shuffle": None
        }

    def _save(self):
        import tempfile
        import os

        self.metadata_file.parent.mkdir(parents=True, exist_ok=True)

        fd, temp_path = tempfile.mkstemp(
            dir=self.metadata_file.parent,
            prefix=f"{self.METADATA_FILENAME}.tmp"
        )

        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(self._state, f, indent=2)

            os.replace(temp_path, self.metadata_file)
        except Exception:
            try:
                os.unlink(temp_path)
            except Exception:
                pass
            raise

    def get_shuffle(self) -> Optional[List[str]]:
        with self._lock:
            shuffle_data = self._state.get('shuffle')
            if not shuffle_data:
                return None
            return shuffle_data.get('order', [])

    def set_shuffle(self, scan_ids: List[str]):
        with self._lock:
            self._state['shuffle'] = {
                'created_at': datetime.now().isoformat(),
                'order': scan_ids
            }
            self._save()

    def clear_shuffle(self):
        with self._lock:
            self._state['shuffle'] = None
            self._save()

    def has_shuffle(self) -> bool:
        with self._lock:
            shuffle_data = self._state.get('shuffle')
            return shuffle_data is not None and len(shuffle_data.get('order', [])) > 0

    def get_shuffle_info(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            shuffle_data = self._state.get('shuffle')
            if not shuffle_data:
                return None
            return {
                'created_at': shuffle_data.get('created_at'),
                'count': len(shuffle_data.get('order', []))
            }
