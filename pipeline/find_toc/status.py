from enum import Enum
from typing import Dict, Any

from infra.storage.book_storage import BookStorage

from .storage import FindTocStageStorage


class FindTocStatus(str, Enum):
    NOT_STARTED = "not_started"
    FINDING = "finding"
    COMPLETED = "completed"


class FindTocStatusTracker:
    def __init__(self, stage_name: str):
        self.stage_name = stage_name
        self.storage = FindTocStageStorage(stage_name=stage_name)

    def get_status(
        self,
        storage: BookStorage
    ) -> Dict[str, Any]:
        finder_result_exists = self.storage.finder_result_exists(storage)

        if finder_result_exists:
            status = FindTocStatus.COMPLETED.value
        else:
            status = FindTocStatus.NOT_STARTED.value

        stage_storage_obj = storage.stage(self.stage_name)
        all_metrics = stage_storage_obj.metrics_manager.get_all()

        total_cost = sum(m.get('cost_usd', 0.0) for m in all_metrics.values())
        total_time = stage_storage_obj.metrics_manager.get_total_time()

        runtime_metrics = stage_storage_obj.metrics_manager.get("stage_runtime")
        stage_runtime = runtime_metrics.get("time_seconds", 0.0) if runtime_metrics else 0.0

        return {
            "status": status,
            "metrics": {
                "total_cost_usd": total_cost,
                "total_time_seconds": total_time,
                "stage_runtime_seconds": stage_runtime,
            },
            "artifacts": {
                "finder_result_exists": finder_result_exists,
            }
        }
