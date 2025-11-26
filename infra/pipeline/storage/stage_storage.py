import json
import os
import threading
from pathlib import Path
from typing import Dict, Any, Optional, Type, TYPE_CHECKING
from pydantic import BaseModel

if TYPE_CHECKING:
    from infra.pipeline.storage.book_storage import BookStorage

class StageStorage:
    """Storage for a single pipeline stage.

    Directories and loggers are created lazily to avoid creating
    empty folders when just reading status.
    """
    def __init__(self, storage: 'BookStorage', name: str):
        self.storage = storage
        self.name = name
        self._lock = threading.RLock()

        # output_dir is a path but NOT created until needed
        self.output_dir = storage.book_dir / name

        # Lazy initialization
        self._metrics_manager = None
        self._logger = None

    def _ensure_output_dir(self):
        """Create output directory if it doesn't exist."""
        if not self.output_dir.exists():
            self.output_dir.mkdir(parents=True, exist_ok=True)

    @property
    def metrics_manager(self):
        """Get metrics manager, creating lazily."""
        if self._metrics_manager is None:
            from infra.pipeline.storage.metrics import MetricsManager
            self._metrics_manager = MetricsManager(self.output_dir / 'metrics.json')
        return self._metrics_manager

    def logger(self):
        """Get logger instance for this stage, creating lazily.

        Log file is written to {book}/{stage}/log.jsonl
        """
        if self._logger is None:
            from infra.pipeline.logger import create_logger
            log_level = "DEBUG" if os.environ.get("DEBUG", "").lower() in ("true", "1", "yes") else "INFO"
            self._logger = create_logger(
                self.storage.scan_id,
                self.name,
                log_dir=self.output_dir,
                level=log_level,
                filename="log.jsonl"
            )
        return self._logger

    def save_page(
        self,
        page_num: int,
        data: Dict[str, Any],
        extension: str = "json",
        schema: Optional[Type[BaseModel]] = None,
        subdir: Optional[str] = None
    ):
        filename = f"page_{page_num:04d}.{extension}"
        if subdir:
            filename = f"{subdir}/{filename}"
        self.save_file(filename, data, schema=schema)

    def load_page(
        self,
        page_num: int,
        extension: str = "json",
        schema: Optional[Type[BaseModel]] = None,
        subdir: Optional[str] = None
    ) -> Dict[str, Any]:
        filename = f"page_{page_num:04d}.{extension}"
        if subdir:
            filename = f"{subdir}/{filename}"
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

            # Ensure parent directories exist (lazy creation)
            output_file.parent.mkdir(parents=True, exist_ok=True)

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

    def list_files(self, pattern: str, subdir: Optional[str] = None) -> list[Path]:
        if subdir:
            search_dir = self.output_dir / subdir
        else:
            search_dir = self.output_dir

        if not search_dir.exists():
            return []

        return sorted(search_dir.glob(pattern))

    def list_pages(self, extension: str = "json", subdir: Optional[str] = None) -> list[int]:
        pattern = f"page_*.{extension}"
        paths = self.list_files(pattern, subdir)

        page_nums = []
        for path in paths:
            page_num_str = path.stem.split('_')[1]
            page_nums.append(int(page_num_str))

        return sorted(page_nums)

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
