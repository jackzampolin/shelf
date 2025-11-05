from typing import Dict, Any, Set
from enum import Enum

from infra.storage.book_storage import BookStorage
from .storage import TesseractStageStorage


class TesseractStatus(str, Enum):
    NOT_STARTED = "not_started"
    RUNNING = "running"
    COMPLETED = "completed"

    @classmethod
    def is_terminal(cls, status: str) -> bool:
        """Check if status represents a terminal state (no more work to do)."""
        return status in [cls.NOT_STARTED.value, cls.COMPLETED.value]

    @classmethod
    def is_in_progress(cls, status: str) -> bool:
        """Check if status represents active processing."""
        return status == cls.RUNNING.value

    @classmethod
    def get_order(cls, status: str) -> int:
        """Get numeric order for status progression (useful for sorting/comparison)."""
        order_map = {
            cls.NOT_STARTED.value: 0,
            cls.RUNNING.value: 1,
            cls.COMPLETED.value: 2,
        }
        return order_map.get(status, 0)


class TesseractStatusTracker:
    def __init__(self, stage_name: str = "tesseract"):
        self.stage_name = stage_name
        self.storage = TesseractStageStorage(stage_name=stage_name)

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
            "status": TesseractStatus.NOT_STARTED.value,
            "metrics": {
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
            return TesseractStatus.NOT_STARTED.value
        elif len(completed_pages) == total_pages:
            return TesseractStatus.COMPLETED.value
        else:
            return TesseractStatus.RUNNING.value

    def _aggregate_metrics(self, storage: BookStorage) -> Dict[str, Any]:
        stage_storage = storage.stage(self.stage_name)

        total_time = stage_storage.metrics_manager.get_total_time()

        runtime_metrics = stage_storage.metrics_manager.get("stage_runtime")
        stage_runtime = runtime_metrics.get("time_seconds", 0.0) if runtime_metrics else 0.0

        return {
            "total_time_seconds": total_time,
            "stage_runtime_seconds": stage_runtime,
        }
