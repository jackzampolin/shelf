"""Book storage with stage-specific views and metrics tracking"""

import json
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional, Type
from abc import ABC, abstractmethod
from pydantic import BaseModel

class StageStorage:
    """
    LOCK ORDERING: Always acquire in this order to prevent deadlocks:
        1. LibraryStorage._lock
        2. BookStorage._metadata_lock
        3. StageStorage._lock
    """

    def __init__(self, storage: 'BookStorage', name: str, dependencies: Optional[List[str]] = None):
        self.storage = storage
        self._name = name
        self._dependencies = dependencies or []
        self._lock = threading.RLock()
        self._metrics_manager = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def output_dir(self) -> Path:
        return self.storage.book_dir / self._name

    @property
    def dependencies(self) -> List[str]:
        return self._dependencies

    def output_page(self, page_num: int, extension: str = "json", subfolder: Optional[str] = None) -> Path:

        base_dir = self.output_dir / subfolder if subfolder else self.output_dir
        return base_dir / f"page_{page_num:04d}.{extension}"

    def list_output_pages(self, extension: str = "json") -> List[Path]:

        if not self.output_dir.exists():
            return []
        pattern = f"page_*.{extension}"
        return sorted(self.output_dir.glob(pattern))

    def ensure_directories(self) -> Dict[str, Path]:

        with self._lock:
            dirs = {
                'output': self.output_dir
            }

            for dir_path in dirs.values():
                dir_path.mkdir(parents=True, exist_ok=True)

            return dirs

    def validate_inputs(self) -> bool:

        if not self.storage.book_dir.exists():
            raise FileNotFoundError(f"Book directory not found: {self.storage.book_dir}")

        for dep in self.dependencies:
            pass

        return True

    @property
    def metrics_manager(self):

        if self._metrics_manager is None:
            with self._lock:
                if self._metrics_manager is None:
                    from infra.storage.metrics import MetricsManager
                    self.ensure_directories()
                    metrics_file = self.output_dir / 'metrics.json'
                    self._metrics_manager = MetricsManager(metrics_file)
        return self._metrics_manager

    def _auto_record_metrics(self, key: str, metrics: Dict[str, Any]) -> None:

        if not metrics:
            return

        # Extract standard fields (matches llm_result_to_metrics output)
        cost_usd = metrics.get('cost_usd', 0.0)
        time_seconds = metrics.get('time_seconds', 0.0)
        tokens = metrics.get('tokens')

        # Remove standard fields + page_num from custom_metrics
        custom = {
            k: v for k, v in metrics.items()
            if k not in ['cost_usd', 'time_seconds', 'tokens', 'page_num']
        }

        self.metrics_manager.record(
            key=key,
            cost_usd=cost_usd,
            time_seconds=time_seconds,
            tokens=tokens,
            custom_metrics=custom if custom else None,
            accumulate=False
        )

    def save_page(
        self,
        page_num: int,
        data: Dict[str, Any],
        cost_usd: float = 0.0,
        processing_time: float = 0.0,
        extension: str = "json",
        metrics: Optional[Dict[str, Any]] = None,
        schema: Optional[Type[BaseModel]] = None
    ):

        if schema:
            validated = schema(**data)
            data = validated.model_dump()

        with self._lock:
            output_file = self.output_page(page_num, extension=extension)
            temp_file = output_file.with_suffix(f'.{extension}.tmp')

            try:
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2)

                temp_file.replace(output_file)

                relative_path = output_file.relative_to(self.output_dir)
                key = str(relative_path.with_suffix(''))
                self._auto_record_metrics(key, metrics)

            except Exception as e:
                if temp_file.exists():
                    temp_file.unlink()
                raise e

    def load_page(
        self,
        page_num: int,
        extension: str = "json",
        subfolder: Optional[str] = None,
        schema: Optional[Type[BaseModel]] = None
    ) -> Dict[str, Any]:

        output_file = self.output_page(page_num, extension=extension, subfolder=subfolder)

        if not output_file.exists():
            raise FileNotFoundError(f"Page {page_num} not found: {output_file}")

        with open(output_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if schema:
            validated = schema(**data)
            return validated.model_dump()

        return data

    def save_file(
        self,
        filename: str,
        data: Dict[str, Any],
        schema: Optional[Type[BaseModel]] = None,
        metrics: Optional[Dict[str, Any]] = None
    ):

        if schema:
            validated = schema(**data)
            data = validated.model_dump()

        with self._lock:
            output_file = self.output_dir / filename
            temp_file = output_file.with_suffix('.tmp')

            try:
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2)

                temp_file.replace(output_file)

                relative_path = output_file.relative_to(self.output_dir)
                key = str(relative_path.with_suffix(''))
                self._auto_record_metrics(key, metrics)

            except Exception as e:
                if temp_file.exists():
                    temp_file.unlink()
                raise e

    def load_file(
        self,
        filename: str,
        schema: Optional[Type[BaseModel]] = None
    ) -> Dict[str, Any]:

        file_path = self.output_dir / filename

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if schema:
            validated = schema(**data)
            return validated.model_dump()

        return data

    def get_log_dir(self) -> Path:

        log_dir = self.output_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir

    def clean_stage(self, confirm: bool = False) -> bool:

        import shutil

        output_files = self.list_output_pages()
        metrics_file = self.output_dir / "metrics.json"
        log_dir = self.output_dir / "logs"
        log_files = list(log_dir.glob("*.jsonl")) if log_dir.exists() else []

        print(f"\n🗑️  Clean {self.name} stage for: {self.storage.scan_id}")
        print(f"   Output files: {len(output_files)}")
        print(f"   Metrics: {'exists' if metrics_file.exists() else 'none'}")
        print(f"   Logs: {len(log_files)} files")

        if not confirm:
            response = input("\n   Proceed? (yes/no): ").strip().lower()
            if response != 'yes':
                print("   Cancelled.")
                return False

        if self.output_dir.exists():
            shutil.rmtree(self.output_dir)
            print(f"   ✓ Deleted {len(output_files)} output files, metrics, and {len(log_files)} log files")

        try:
            self.storage.update_metadata({
                f'{self.name}_complete': False,
                f'{self.name}_completion_date': None,
                f'{self.name}_total_cost': None
            })
            print(f"   ✓ Reset metadata")
        except FileNotFoundError:
            pass

        print(f"\n✅ {self.name.capitalize()} stage cleaned for {self.storage.scan_id}")
        return True

class BookStorage:

    def __init__(self, scan_id: str, storage_root: Optional[Path] = None):

        self._scan_id = scan_id
        self._storage_root = Path(storage_root or Path.home() / "Documents" / "book_scans").expanduser()
        self._book_dir = self._storage_root / scan_id

        self._stage_cache: Dict[str, StageStorage] = {}

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

    def list_stages(self) -> List[str]:

        if not self.book_dir.exists():
            return []

        stages = []
        for item in self.book_dir.iterdir():
            if item.is_dir() and not item.name.startswith('.'):
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
            'has_source_pages': len(source_stage.list_output_pages(extension='png')) > 0
        }
