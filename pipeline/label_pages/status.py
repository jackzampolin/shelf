from enum import Enum
from typing import Dict, Any

from infra.storage.book_storage import BookStorage

from .storage import LabelPagesStageStorage


class LabelPagesStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class LabelPagesStatusTracker:
    def __init__(self, stage_name: str):
        self.stage_name = stage_name
        self.storage = LabelPagesStageStorage(stage_name=stage_name)

    def get_status(
        self,
        storage: BookStorage
    ) -> Dict[str, Any]:
        """Get label-pages status (simplified single-stage)."""
        metadata = storage.load_metadata()
        total_pages = metadata.get('total_pages', 0)

        if total_pages == 0:
            raise ValueError("total_pages not set in metadata")

        completed_pages = self.storage.list_completed_pages(storage)

        remaining_pages = [
            p for p in range(1, total_pages + 1)
            if p not in completed_pages
        ]

        # Determine status
        if len(completed_pages) == 0:
            status = LabelPagesStatus.NOT_STARTED.value
        elif len(remaining_pages) > 0:
            status = LabelPagesStatus.IN_PROGRESS.value
        else:
            status = LabelPagesStatus.COMPLETED.value

        # Aggregate metrics
        stage_storage = storage.stage(self.stage_name)
        all_metrics = stage_storage.metrics_manager.get_all()

        total_cost = 0.0
        total_tokens = 0

        for metrics in all_metrics.values():
            total_cost += metrics.get('cost_usd', 0.0)
            usage = metrics.get('usage', {})
            if usage:
                total_tokens += usage.get('completion_tokens', 0)
                total_tokens += usage.get('prompt_tokens', 0)

        total_time = stage_storage.metrics_manager.get_total_time()

        runtime_metrics = stage_storage.metrics_manager.get("stage_runtime")
        stage_runtime = runtime_metrics.get("time_seconds", 0.0) if runtime_metrics else 0.0

        return {
            "status": status,
            "total_pages": total_pages,
            "completed_pages": len(completed_pages),
            "remaining_pages": remaining_pages,
            "metrics": {
                "total_cost_usd": total_cost,
                "total_tokens": total_tokens,
                "total_time_seconds": total_time,
                "stage_runtime_seconds": stage_runtime,
            },
            "artifacts": {},
        }
