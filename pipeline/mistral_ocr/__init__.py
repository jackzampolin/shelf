from typing import Dict, Any

from infra.pipeline.base_stage import BaseStage
from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.status import BatchBasedStatusTracker
from .tools.processor import process_batch


class MistralOcrStage(BaseStage):
    name = "mistral-ocr"
    dependencies = []  # Can run directly on source images

    @classmethod
    def default_kwargs(cls, **overrides):
        return {
            'max_workers': overrides.get('workers', 10),
            'model': overrides.get('model') or 'mistral-ocr-latest',
            'include_images': overrides.get('include_images', False)
        }

    def __init__(
        self,
        storage: BookStorage,
        max_workers: int = 10,
        model: str = "mistral-ocr-latest",
        include_images: bool = False
    ):
        super().__init__(storage)
        self.max_workers = max_workers
        self.model = model
        self.include_images = include_images

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
            storage=self.storage,
            logger=self.logger,
            remaining_pages=remaining_pages,
            max_workers=self.max_workers,
            model=self.model,
            include_images=self.include_images
        )
