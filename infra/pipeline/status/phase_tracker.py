from typing import Any, Callable, Dict, List, Optional, Set
from pathlib import Path
import shutil

from infra.pipeline.storage.stage_storage import StageStorage


class PhaseStatusTracker:
    def __init__(
        self,
        stage_storage: StageStorage,
        phase_name: str,
        discoverer: Callable[[Path], List[Any]],
        output_path_fn: Callable[[Any, Path], Path],
        run_fn: Callable[['PhaseStatusTracker', Any], None],
        use_subdir: bool = False,
        run_kwargs: Optional[Dict[str, Any]] = None,
        validator_override: Optional[Callable[[Any, Path], bool]] = None,
    ):
        self.stage_storage = stage_storage
        self.logger = stage_storage.logger()
        self.phase_name = phase_name
        self.storage = stage_storage.storage
        self.metrics_manager = stage_storage.metrics_manager
        self.use_subdir = use_subdir

        if use_subdir:
            self.phase_dir = stage_storage.output_dir / phase_name
        else:
            self.phase_dir = stage_storage.output_dir

        self.phase_dir.mkdir(parents=True, exist_ok=True)

        self.metrics_prefix = f"{phase_name}_"

        self._discoverer = lambda: discoverer(self.phase_dir)
        self._output_path_fn = lambda item: output_path_fn(item, self.phase_dir)

        if validator_override:
            self._validator = lambda item: validator_override(item, self.phase_dir)
        else:
            self._validator = lambda item: self._output_path_fn(item).exists()

        self._run_fn = run_fn
        self._run_kwargs = run_kwargs or {}

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

    def run(self) -> None:
        self._run_fn(self, **self._run_kwargs)

    def output_path(self, item: Any) -> Path:
        """Get the output path for an item."""
        return self._output_path_fn(item)

    def clean(self) -> Dict[str, Any]:
        """Clean all outputs for this phase."""
        items = self._discoverer()
        deleted = []

        for item in items:
            path = self._output_path_fn(item)
            if path.exists():
                path.unlink()
                deleted.append(str(path))

        # Remove phase subdir if empty and using subdir
        if self.use_subdir and self.phase_dir.exists():
            try:
                if not any(self.phase_dir.iterdir()):
                    self.phase_dir.rmdir()
            except OSError:
                pass  # Directory not empty or other issue

        return {"phase": self.phase_name, "deleted_count": len(deleted), "deleted": deleted}