from typing import Dict, Any

from infra.config import Config
from infra.pipeline.base_stage import BaseStage
from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.status import BatchBasedStatusTracker
from .batch import process_pages


class LabelStructureStage(BaseStage):
    name = "label-structure"
    dependencies = ["mistral-ocr", "olm-ocr", "paddle-ocr"]

    @classmethod
    def default_kwargs(cls, **overrides):
        kwargs = {'max_retries': overrides.get('max_retries', 3)}
        if 'model' in overrides and overrides['model']:
            kwargs['model'] = overrides['model']
        if 'workers' in overrides and overrides['workers']:
            kwargs['max_workers'] = overrides['workers']
        return kwargs

    def __init__(
        self,
        storage: BookStorage,
        model: str = None,
        max_workers: int = None,
        max_retries: int = 3,
    ):
        super().__init__(storage)

        self.model = model or Config.text_model_primary
        self.max_workers = max_workers or Config.max_workers
        self.max_retries = max_retries

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
        if not remaining_pages:
            self.logger.info("No pages to process")
            return {"status": "success", "pages_processed": 0, "cost_usd": 0.0}

        process_pages(
            tracker=self.status_tracker,
            model=self.model,
            max_workers=self.max_workers,
            max_retries=self.max_retries,
        )

        return {"status": "success"}
