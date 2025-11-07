from typing import Dict, List, Any, Optional

from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger


class BaseStage:
    name: str = None
    dependencies: List[str] = []
    status_tracker: Optional[Any] = None

    def get_status(
        self,
        storage: BookStorage,
        logger: PipelineLogger
    ) -> Dict[Any, Any]:
        if self.status_tracker:
            return self.status_tracker.get_status(storage, logger)

        raise NotImplementedError(
            f"{self.__class__.__name__} must implement get_status() method or set status_tracker"
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

    def before(self, storage: BookStorage, logger: PipelineLogger) -> None:
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement before() method: check the dependancy stage(s) status is complete"
        )

    def run(
        self,
        storage: BookStorage,
        logger: PipelineLogger
    ) -> Dict[str, Any]:
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement run() method: the thing that this stage does"
        )
