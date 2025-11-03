from enum import Enum
from typing import Dict, Any

from infra.storage.book_storage import BookStorage

from .storage import ParagraphCorrectStageStorage


class ParagraphCorrectStatus(str, Enum):
    NOT_STARTED = "not_started"
    CORRECTING = "correcting"
    GENERATING_REPORT = "generating_report"
    COMPLETED = "completed"


class ParagraphCorrectStatusTracker:

    def __init__(self, stage_name: str):
        self.stage_name = stage_name
        self.storage = ParagraphCorrectStageStorage(stage_name=stage_name)

    def get_status(
        self,
        storage: BookStorage,
    ) -> Dict[str, Any]:

        metadata = storage.load_metadata()
        total_pages = metadata.get('total_pages', 0)

        if total_pages == 0:
            raise ValueError("total_pages not set in metadata")

        completed_pages = self.storage.list_completed_pages(storage)
        remaining_pages = [
            p for p in range(1, total_pages + 1)
            if p not in completed_pages
        ]

        report_exists = self.storage.report_exists(storage)
        if len(remaining_pages) == total_pages:
            status = ParagraphCorrectStatus.NOT_STARTED.value
        elif len(remaining_pages) > 0:
            status = ParagraphCorrectStatus.CORRECTING.value
        elif not report_exists:
            status = ParagraphCorrectStatus.GENERATING_REPORT.value
        else:
            status = ParagraphCorrectStatus.COMPLETED.value

        stage_storage = storage.stage(self.stage_name)

        total_cost = stage_storage.metrics_manager.get_total_cost()
        total_time = stage_storage.metrics_manager.get_total_time()
        total_tokens = stage_storage.metrics_manager.get_total_tokens()

        # Get stored runtime from stage execution (actual wall-clock processing time)
        # This is the actual time spent processing, excluding gaps/interruptions
        # Shows 0.0 until the stage has been run with runtime tracking enabled
        runtime_metrics = stage_storage.metrics_manager.get("stage_runtime")
        stage_runtime = runtime_metrics.get("time_seconds", 0.0) if runtime_metrics else 0.0

        all_metrics = stage_storage.metrics_manager.get_all()
        total_corrections = 0
        confidences = []

        for metrics in all_metrics.values():
            total_corrections += metrics.get('total_corrections', 0)

            conf = metrics.get('avg_confidence')
            if conf is not None:
                confidences.append(conf)

        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        return {
            "status": status,
            "total_pages": total_pages,
            "remaining_pages": remaining_pages,
            "metrics": {
                "total_cost_usd": total_cost,
                "total_tokens": total_tokens,
                "total_time_seconds": total_time,
                "stage_runtime_seconds": stage_runtime,
                "total_corrections": total_corrections,
                "avg_confidence": avg_confidence,
            },
            "artifacts": {
                "report_exists": report_exists,
            },
        }
