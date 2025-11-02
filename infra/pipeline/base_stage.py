from typing import Dict, List, Any

from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger


class BaseStage:
    name: str = None
    dependencies: List[str] = []

    def get_status(
        self,
        storage: BookStorage,
        logger: PipelineLogger
    ) -> Dict[Any, Any]:
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement get_status() method: the progress to completion"
        )

    def pretty_print_status(self, status: Dict[str, Any]) -> str:
        """Return formatted status string for CLI display.

        Default implementation handles common fields.
        Subclasses can override to add stage-specific formatting.
        """
        lines = []

        stage_status = status.get('status', 'unknown')
        remaining = len(status.get('remaining_pages', []))
        total = status.get('total_pages', 0)
        completed = total - remaining

        lines.append(f"   Status: {stage_status}")
        lines.append(f"   Pages:  {completed}/{total} ({remaining} remaining)")

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
