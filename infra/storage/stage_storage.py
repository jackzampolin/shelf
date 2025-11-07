import json
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional, Type, TYPE_CHECKING
from pydantic import BaseModel

if TYPE_CHECKING:
    from infra.storage.book_storage import BookStorage

class StageStorage:
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

    def save_page(
        self,
        page_num: int,
        data: Dict[str, Any],
        extension: str = "json",
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

    def load_page_image(self, page_num: int, extension: str = "png") -> Path:
        image_file = self.output_page(page_num, extension=extension)

        if not image_file.exists():
            raise FileNotFoundError(f"Image for page {page_num} not found: {image_file}")

        return image_file

    def save_file(
        self,
        filename: str,
        data: Dict[str, Any],
        schema: Optional[Type[BaseModel]] = None
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
