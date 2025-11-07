import os
from typing import Dict, List, Any

from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import create_logger
from infra.pipeline.registry import get_stage_class


class BaseStage:
    name: str = None
    dependencies: List[str] = []
    status_tracker: Any = None

    def __init__(self, storage: BookStorage):
        self.storage = storage
        self.stage_storage = storage.stage(self.name)

        logs_dir = self.stage_storage.output_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        log_level = "DEBUG" if os.environ.get("DEBUG", "").lower() in ("true", "1") else "INFO"
        self.logger = create_logger(storage.scan_id, self.name, log_dir=logs_dir, level=log_level)

    def get_status(self) -> Dict[Any, Any]:
        if not self.status_tracker:
            raise RuntimeError(
                f"{self.__class__.__name__} must set status_tracker in __init__"
            )
        return self.status_tracker.get_status()

    def check_source_exists(self) -> None:
        source_stage = self.storage.stage("source")
        source_pages = source_stage.list_output_pages(extension="png")

        if len(source_pages) == 0:
            raise ValueError("No source pages found - cannot run this stage")

    def check_dependency_completed(self, dependency_stage) -> None:
        status = dependency_stage.get_status()
        stage_status = status.get('status', 'unknown')

        if stage_status != 'completed':
            raise RuntimeError(
                f"{dependency_stage.name} stage is not completed (status: {stage_status}). "
                f"Run {dependency_stage.name} stage to completion first."
            )

    def pretty_print_status(self, status: Dict[str, Any]) -> str:
        lines = []

        stage_status = status.get('status', 'unknown')

        progress = status.get('progress', {})
        remaining = progress.get('remaining_items', progress.get('remaining_pages', []))
        total = progress.get('total_items', progress.get('total_pages', 0))
        completed = progress.get('completed_items', progress.get('completed_pages', 0))

        if isinstance(remaining, list):
            remaining = len(remaining)

        lines.append(f"   Status: {stage_status}")

        if total > 0:
            lines.append(f"   Items:  {completed}/{total} ({remaining} remaining)")

        metrics = status.get('metrics', {})
        if metrics.get('total_cost_usd', 0) > 0:
            lines.append(f"   Cost:   ${metrics['total_cost_usd']:.4f}")
        if metrics.get('total_time_seconds', 0) > 0:
            mins = metrics['total_time_seconds'] / 60
            lines.append(f"   Time:   {mins:.1f}m")

        return '\n'.join(lines)

    def before(self) -> None:
        self.check_source_exists()

        for dep_name in self.dependencies:
            dep_class = get_stage_class(dep_name)
            dep_stage = dep_class(self.storage)
            self.check_dependency_completed(dep_stage)

    def run(self) -> Dict[str, Any]:
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement run() method: the thing that this stage does"
        )
