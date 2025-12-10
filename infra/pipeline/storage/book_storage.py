import json
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional

from infra.pipeline.storage.stage_storage import StageStorage
from infra.pipeline.storage.source_storage import SourceStorage

class BookStorage:
    def __init__(self, scan_id: str, storage_root: Optional[Path] = None):
        self._scan_id = scan_id
        self._storage_root = Path(storage_root or Path.home() / "Documents" / "shelf").expanduser()
        self._book_dir = self._storage_root / scan_id

        self._stage_cache: Dict[str, StageStorage] = {}
        self._source_storage: Optional[SourceStorage] = None

        self._metadata_lock = threading.Lock()

    @property
    def scan_id(self) -> str:
        return self._scan_id

    @property
    def storage_root(self) -> Path:
        return self._storage_root

    @property
    def book_dir(self) -> Path:
        return self._book_dir

    @property
    def exists(self) -> bool:
        return self._book_dir.exists()

    def stage(self, name: str) -> StageStorage:
        if name not in self._stage_cache:
            self._stage_cache[name] = StageStorage(self, name)
        return self._stage_cache[name]

    def source(self) -> SourceStorage:
        if self._source_storage is None:
            self._source_storage = SourceStorage(self)
        return self._source_storage

    def list_stages(self) -> List[str]:
        if not self.book_dir.exists():
            return []

        stages = []
        for item in self.book_dir.iterdir():
            if not item.is_dir() or item.name.startswith('.'):
                continue
            if (item / "metrics.json").exists() or list(item.glob("page_*.json")):
                stages.append(item.name)
        return sorted(stages)

    def has_stage(self, name: str) -> bool:
        return (self.book_dir / name).exists()

    def stage_status(self, name: str) -> Dict[str, Any]:
        return {'status': 'not_started'}

    @property
    def metadata_file(self) -> Path:
        return self._book_dir / "metadata.json"

    def _load_metadata_unsafe(self) -> Dict[str, Any]:
        if not self.metadata_file.exists():
            raise FileNotFoundError(f"Metadata file not found: {self.metadata_file}")

        with open(self.metadata_file, 'r') as f:
            return json.load(f)

    def _save_metadata_unsafe(self, metadata: Dict[str, Any]):
        temp_file = self.metadata_file.with_suffix('.json.tmp')
        with open(temp_file, 'w') as f:
            json.dump(metadata, f, indent=2)
        temp_file.replace(self.metadata_file)

    def load_metadata(self) -> Dict[str, Any]:
        with self._metadata_lock:
            return self._load_metadata_unsafe()

    def save_metadata(self, metadata: Dict[str, Any]):
        with self._metadata_lock:
            self._save_metadata_unsafe(metadata)

    def update_metadata(self, updates: Dict[str, Any]):
        with self._metadata_lock:
            metadata = self._load_metadata_unsafe()
            metadata.update(updates)
            self._save_metadata_unsafe(metadata)

    def validate_book(self) -> Dict[str, bool]:
        source_stage = self.stage('source')
        return {
            'book_dir_exists': self.book_dir.exists(),
            'metadata_exists': self.metadata_file.exists(),
            'source_dir_exists': source_stage.output_dir.exists(),
            'has_source_pages': len(source_stage.list_pages(extension='png')) > 0
        }
