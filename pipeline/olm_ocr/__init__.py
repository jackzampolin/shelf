from typing import Dict, Any

from infra.pipeline.base_stage import BaseStage
from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.status import BatchBasedStatusTracker
from .tools.processor import process_batch

class OlmOcrStage(BaseStage):
    name = "olm-ocr"
    dependencies = []

    @classmethod
    def default_kwargs(cls, **overrides):
        return {'max_workers': overrides.get('workers', 30)}

    def __init__(self, storage: BookStorage, max_workers: int = 30):
        super().__init__(storage)
        self.max_workers = max_workers
        self.status_tracker = BatchBasedStatusTracker(
            storage=self.storage,
            logger=self.logger,
            stage_name=self.name,
            item_pattern="page_{:04d}.json"
        )

    def run(self) -> Dict[str, Any]:
        if self.status_tracker.is_completed():
            return self.status_tracker.get_skip_response()

        remaining_pages = self.status_tracker.get_remaining_items()

        return process_batch(
            self.storage,
            self.logger,
            remaining_pages,
            self.max_workers
        )
