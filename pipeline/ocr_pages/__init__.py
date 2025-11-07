from typing import Dict, Any

from infra.pipeline.base_stage import BaseStage
from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.pipeline.status import BatchBasedStatusTracker

from .schemas import OcrPagesPageOutput
from .tools.processor import process_batch


class OcrPagesStage(BaseStage):
    name = "ocr-pages"
    dependencies = ["source"]

    output_schema = OcrPagesPageOutput
    checkpoint_schema = None
    report_schema = None
    self_validating = True

    def __init__(self, max_workers: int = 30):
        super().__init__()
        self.max_workers = max_workers
        self.status_tracker = BatchBasedStatusTracker(
            stage_name=self.name,
            source_stage="source",
            item_pattern="page_{:04d}.json"
        )

    def before(
        self,
        storage: BookStorage,
        logger: PipelineLogger
    ):
        logger.info(f"OCR-Pages with OlmOCR (max_workers={self.max_workers})")

        source_stage = storage.stage("source")
        source_pages = source_stage.list_output_pages(extension="png")

        if len(source_pages) == 0:
            raise ValueError("No source pages found - cannot run ocr-pages stage")

        logger.info(f"Found {len(source_pages)} source pages")

    def run(
        self,
        storage: BookStorage,
        logger: PipelineLogger,
    ) -> Dict[str, Any]:
        if self.status_tracker.is_completed(storage, logger):
            return self.status_tracker.get_skip_response(storage, logger)

        remaining_pages = self.status_tracker.get_remaining_items(storage, logger)

        return process_batch(
            storage,
            logger,
            remaining_pages,
            self.max_workers
        )
