from typing import Dict, Any

from infra.pipeline.base_stage import BaseStage
from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.status import page_batch_tracker
from infra.ocr import OCRBatchProcessor
from .provider import OlmOCRProvider
from .schemas import OlmOcrPageOutput, OlmOcrPageMetrics


class OlmOcrStage(BaseStage):
    name = "olm-ocr"
    dependencies = []

    @classmethod
    def default_kwargs(cls, **overrides):
        return {'max_workers': overrides.get('workers', 30)}

    def __init__(self, storage: BookStorage, max_workers: int = 30):
        super().__init__(storage)
        self.max_workers = max_workers

        def run_ocr(tracker, **kwargs):
            processor = OCRBatchProcessor(
                provider=OlmOCRProvider(tracker.stage_storage),
                status_tracker=tracker,
                max_workers=self.max_workers,
            )
            return processor.process_batch()

        self.status_tracker = page_batch_tracker(
            stage_storage=self.stage_storage,
            phase_name="ocr",
            run_fn=run_ocr,
            extension="json",
            use_subdir=False,
        )

    def run(self) -> Dict[str, Any]:
        if self.status_tracker.is_completed():
            return {"status": "skipped", "reason": "already completed"}

        batch_stats = self.status_tracker.run()

        return {
            "status": batch_stats["status"],
            "pages_processed": batch_stats["pages_processed"],
            "cost_usd": batch_stats["total_cost"]
        }


__all__ = [
    "OlmOcrStage",
    "OlmOCRProvider",
    "OlmOcrPageOutput",
    "OlmOcrPageMetrics",
]
