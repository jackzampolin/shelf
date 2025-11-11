from typing import Dict, Any

from infra.pipeline.base_stage import BaseStage
from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.status import BatchBasedStatusTracker
from infra.ocr import OCRBatchProcessor
from .olmocr import OlmOCRProvider
from .schemas import OlmOcrPageOutput


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

        # Initialize provider and batch processor
        self.provider = OlmOCRProvider()
        self.processor = OCRBatchProcessor(
            provider=self.provider,
            storage=self.storage,
            logger=self.logger,
            max_workers=self.max_workers,
        )

    def run(self) -> Dict[str, Any]:
        if self.status_tracker.is_completed():
            return self.status_tracker.get_skip_response()

        remaining_pages = self.status_tracker.get_remaining_items()
        stage_storage = self.storage.stage(self.name)

        def handle_result(page_num: int, result):
            """Callback for each successful OCR result."""
            # Build output with provider metadata
            output = OlmOcrPageOutput(
                page_num=page_num,
                text=result.text,
                char_count=len(result.text),
                **result.metadata  # OlmOCR-specific fields
            )

            # Save to disk
            stage_storage.save_page(page_num, output.model_dump(), schema=OlmOcrPageOutput)

            # Record metrics
            stage_storage.metrics_manager.record(
                key=f"page_{page_num:04d}",
                cost_usd=result.cost_usd,
                time_seconds=result.execution_time_seconds,
                custom_metrics={
                    "page": page_num,
                    "char_count": len(result.text),
                    "prompt_tokens": result.prompt_tokens,
                    "completion_tokens": result.completion_tokens,
                }
            )

        # Process batch
        batch_stats = self.processor.process_batch(
            page_nums=remaining_pages,
            on_result=handle_result
        )

        return {
            "status": batch_stats["status"],
            "pages_processed": batch_stats["pages_processed"],
            "cost_usd": batch_stats["total_cost"]
        }
