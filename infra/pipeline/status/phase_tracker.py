from typing import Any, Callable, Dict, List, Optional, Set
from pathlib import Path

from infra.pipeline.storage.stage_storage import StageStorage

class PhaseStatusTracker:
    def __init__(
        self,
        stage_storage: StageStorage,
        phase_name: str,
        discoverer: Callable[[Path], List[Any]],
        validator: Callable[[Any, Path], bool],
        use_subdir: bool = False,
    ):
        self.stage_storage = stage_storage
        self.logger = stage_storage.logger()
        self.phase_name = phase_name

        if use_subdir:
            self.phase_dir = stage_storage.output_dir / phase_name
        else:
            self.phase_dir = stage_storage.output_dir

        self.metrics_prefix = f"{phase_name}_"

        self._discoverer = lambda: discoverer(self.phase_dir)
        self._validator = lambda item: validator(item, self.phase_dir)

    def is_completed(self) -> bool:
        return len(self.get_remaining_items()) == 0

    def get_status(self, metrics=False) -> Dict[str, Any]:
        all_items = set(self._discoverer())
        completed = {item for item in all_items if self._validator(item)}
        remaining = sorted(all_items - completed)

        if len(completed) == 0:
            status = "not_started"
        elif len(remaining) == 0:
            status = "completed"
        else:
            status = "in_progress"

        if metrics:
            rollup = self.get_phase_metrics()
            return {
                "status": status,
                "phase": self.phase_name,
                "progress": {
                    "total_items": len(all_items),
                    "completed_items": len(completed),
                    "remaining_items": remaining,
                },
                "metrics": rollup,
            }
        else:
            return {
                "status": status,
                "phase": self.phase_name,
                "progress": {
                    "total_items": len(all_items),
                    "completed_items": len(completed),
                    "remaining_items": remaining,
                },
            }

    def get_remaining_items(self) -> List[Any]:
        all_items = set(self._discoverer())
        completed = {item for item in all_items if self._validator(item)}
        remaining = all_items - completed
        return sorted(remaining)

    def get_phase_metrics(self) -> Dict[str, Any]:
        return self.stage_storage.metrics_manager.get_cumulative_metrics(
            prefix=self.metrics_prefix
        )

    def get_phase_metric_records(self) -> Dict[str, Dict[str, Any]]:
        return self.stage_storage.metrics_manager.get_metrics_by_prefix(
            prefix=self.metrics_prefix
        )