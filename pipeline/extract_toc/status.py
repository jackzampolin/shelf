import time
from enum import Enum
from typing import Dict, Any

from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger

from .storage import ExtractTocStageStorage


class ExtractTocStatus(str, Enum):
    NOT_STARTED = "not_started"
    EXTRACTING_ENTRIES = "extracting_entries"
    ASSEMBLING = "assembling"
    COMPLETED = "completed"


class ExtractTocStatusTracker:

    def __init__(self, stage_name: str):
        self.stage_name = stage_name
        self.storage = ExtractTocStageStorage(stage_name=stage_name)

    def get_status(
        self,
        storage: BookStorage
    ) -> Dict[str, Any]:

        entries_extracted_exists = self.storage.entries_extracted_exists(storage)
        toc_validated_exists = self.storage.toc_validated_exists(storage)

        if not entries_extracted_exists:
            status = ExtractTocStatus.EXTRACTING_ENTRIES.value
        elif not toc_validated_exists:
            status = ExtractTocStatus.ASSEMBLING.value
        else:
            status = ExtractTocStatus.COMPLETED.value

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
                "entries_extracted_exists": entries_extracted_exists,
                "toc_validated_exists": toc_validated_exists,
            }
        }
