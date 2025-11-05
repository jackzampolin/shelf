from typing import Dict, Any, Set
from enum import Enum

from infra.storage.book_storage import BookStorage
from .storage import OcrPagesStageStorage


class OcrPagesStatus(str, Enum):
    NOT_STARTED = "not_started"
    RUNNING = "running"
    COMPLETED = "completed"


class OcrPagesStatusTracker:
    def __init__(self, stage_name: str = "ocr-pages"):
        self.stage_name = stage_name
        self.storage = OcrPagesStageStorage(stage_name=stage_name)

    def get_status(
        self,
        storage: BookStorage,
    ) -> Dict[str, Any]:
        source_stage = storage.stage("source")
        source_pages = source_stage.list_output_pages(extension="png")
        total_pages = len(source_pages)

        if total_pages == 0:
            return self._empty_progress()

        all_pages = set(range(1, total_pages + 1))
        completed_pages = self._get_completed_pages(storage, all_pages)
        remaining_pages = sorted(all_pages - completed_pages)

        status = self._determine_status(completed_pages, total_pages)
        metrics = self._aggregate_metrics(storage)

        return {
            "total_pages": total_pages,
            "remaining_pages": remaining_pages,
            "completed_pages": len(completed_pages),
            "status": status,
            "metrics": metrics,
        }

    def _empty_progress(self) -> Dict[str, Any]:
        return {
            "total_pages": 0,
            "remaining_pages": [],
            "completed_pages": 0,
            "status": OcrPagesStatus.NOT_STARTED.value,
            "metrics": {
                "total_cost_usd": 0.0,
                "total_tokens": 0,
                "total_time_seconds": 0.0,
                "stage_runtime_seconds": 0.0,
            },
        }

    def _get_completed_pages(
        self,
        storage: BookStorage,
        all_pages: Set[int]
    ) -> Set[int]:
        completed = set()

        for page_num in all_pages:
            if self.storage.page_exists(storage, page_num):
                completed.add(page_num)

        return completed

    def _determine_status(
        self,
        completed_pages: Set[int],
        total_pages: int
    ) -> str:
        if len(completed_pages) == 0:
            return OcrPagesStatus.NOT_STARTED.value
        elif len(completed_pages) == total_pages:
            return OcrPagesStatus.COMPLETED.value
        else:
            return OcrPagesStatus.RUNNING.value

    def _aggregate_metrics(self, storage: BookStorage) -> Dict[str, Any]:
        stage_storage = storage.stage(self.stage_name)

        total_cost = stage_storage.metrics_manager.get_total_cost()
        total_time = stage_storage.metrics_manager.get_total_time()
        total_tokens = stage_storage.metrics_manager.get_total_tokens()

        # Get stage runtime (actual wall-clock processing time)
        runtime_metrics = stage_storage.metrics_manager.get("stage_runtime")
        stage_runtime = runtime_metrics.get("time_seconds", 0.0) if runtime_metrics else 0.0

        return {
            "total_cost_usd": total_cost,
            "total_tokens": total_tokens,
            "total_time_seconds": total_time,
            "stage_runtime_seconds": stage_runtime,
        }
