import json
import threading
from pathlib import Path
from typing import Dict, Any, Optional, Type, TYPE_CHECKING
from pydantic import BaseModel

if TYPE_CHECKING:
    from infra.storage.book_storage import BookStorage

class StageStorage:
    def __init__(self, storage: 'BookStorage', name: str):
        self.storage = storage
        self.name = name
        self._lock = threading.RLock()

        from infra.storage.metrics import MetricsManager
        self.output_dir = storage.book_dir / name
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.metrics_manager = MetricsManager(self.output_dir / 'metrics.json')

    def save_page(
        self,
        page_num: int,
        data: Dict[str, Any],
        extension: str = "json",
        schema: Optional[Type[BaseModel]] = None
    ):
        filename = f"page_{page_num:04d}.{extension}"
        self.save_file(filename, data, schema=schema)

    def load_page(
        self,
        page_num: int,
        extension: str = "json",
        schema: Optional[Type[BaseModel]] = None
    ) -> Dict[str, Any]:
        filename = f"page_{page_num:04d}.{extension}"
        return self.load_file(filename, schema=schema)

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

    def list_pages(self, extension: str = "json") -> list[int]:
        if not self.output_dir.exists():
            return []

        page_nums = []
        pattern = f"page_*.{extension}"
        for path in self.output_dir.glob(pattern):
            page_num_str = path.stem.split('_')[1]
            page_nums.append(int(page_num_str))

        return sorted(page_nums)

    def get_log_dir(self) -> Path:
        log_dir = self.output_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir

    def clean(self):
        import shutil

        if self.output_dir.exists():
            shutil.rmtree(self.output_dir)

        try:
            self.storage.update_metadata({
                f'{self.name}_complete': False,
                f'{self.name}_completion_date': None,
                f'{self.name}_total_cost': None
            })
        except FileNotFoundError:
            pass
