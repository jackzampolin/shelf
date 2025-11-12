from typing import Dict, Any

from infra.pipeline.base_stage import BaseStage
from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.status import BatchBasedStatusTracker
from infra.ocr import OCRBatchProcessor
from .provider import MistralOCRProvider
from .schemas import MistralOcrPageOutput, ImageBBox, PageDimensions


class MistralOcrStage(BaseStage):
    name = "mistral-ocr"
    dependencies = []

    @classmethod
    def default_kwargs(cls, **overrides):
        return {
            'max_workers': overrides.get('workers', 10),
            'include_images': overrides.get('include_images', False)
        }

    def __init__(
        self,
        storage: BookStorage,
        max_workers: int = 10,
        include_images: bool = False
    ):
        super().__init__(storage)
        self.max_workers = max_workers
        self.include_images = include_images
        self.status_tracker = BatchBasedStatusTracker(
            storage=self.storage,
            logger=self.logger,
            stage_name=self.name,
            item_pattern="page_{:04d}.json"
        )

        self.processor = OCRBatchProcessor(
            provider=MistralOCRProvider(
                self.storage.stage(self.name),
                include_images=self.include_images
            ),
            status_tracker=self.status_tracker,
            max_workers=self.max_workers,
        )

    def run(self) -> Dict[str, Any]:
        if self.status_tracker.is_completed():
            return self.status_tracker.get_skip_response()

        batch_stats = self.processor.process_batch()

        return {
            "status": batch_stats["status"],
            "pages_processed": batch_stats["pages_processed"],
            "cost_usd": batch_stats["total_cost"]
        }


__all__ = [
    "MistralOcrStage",
    "MistralOCRProvider",
    "MistralOcrPageOutput",
    "ImageBBox",
    "PageDimensions",
]
