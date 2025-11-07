from typing import Dict, Any, List
from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger


class BatchBasedStatusTracker:
    def __init__(
        self,
        storage: BookStorage,
        logger: PipelineLogger,
        stage_name: str,
        item_pattern: str = "page_{:04d}.json"
    ):
        self.storage = storage
        self.logger = logger
        self.stage_name = stage_name
        self.item_pattern = item_pattern

    def is_completed(self) -> bool:
        status = self.get_status()
        return status["status"] == "completed"

    def get_remaining_items(self) -> List[int]:
        status = self.get_status()
        return status["progress"]["remaining_items"]

    def has_work(self) -> bool:
        return len(self.get_remaining_items()) > 0

    def get_skip_response(self) -> Dict[str, Any]:
        status = self.get_status()
        return {
            "status": "skipped",
            "reason": "already completed",
            "items_processed": status["progress"]["completed_items"]
        }

    def get_no_work_response(self) -> Dict[str, Any]:
        return {
            "status": "success",
            "items_processed": 0
        }

    def get_status(self) -> Dict[str, Any]:
        source_pages = self.storage.stage("source").list_pages(extension="png")
        total = len(source_pages)

        all_page_nums = set(range(1, total + 1))

        stage_storage = self.storage.stage(self.stage_name)

        extension = self.item_pattern.split('.')[-1]
        completed = set(stage_storage.list_pages(extension=extension))

        remaining = sorted(all_page_nums - completed)

        if len(completed) == 0:
            status = "not_started"
        elif len(remaining) == 0:
            status = "completed"
        else:
            status = "in_progress"

        metrics = stage_storage.metrics_manager.get_aggregated()

        return {
            "status": status,
            "progress": {
                "total_items": total,
                "completed_items": len(completed),
                "remaining_items": remaining,
            },
            "metrics": metrics,
        }

    def _item_exists(self, stage_storage, item_num: int) -> bool:
        filename = self.item_pattern.format(item_num)
        return (stage_storage.output_dir / filename).exists()
