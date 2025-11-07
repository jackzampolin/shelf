import multiprocessing
from typing import Dict, Any

from infra.pipeline.base_stage import BaseStage
from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.pipeline.status import BatchBasedStatusTracker

from .schemas import TesseractPageOutput
from .tools.processor import process_batch


class TesseractStage(BaseStage):
    name = "tesseract"
    dependencies = ["source"]

    output_schema = TesseractPageOutput
    checkpoint_schema = None
    report_schema = None
    self_validating = True

    def __init__(self, psm_mode: int = 3, max_workers: int = None):
        super().__init__()
        self.psm_mode = psm_mode
        self.max_workers = max_workers or multiprocessing.cpu_count()
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
        logger.info(f"Tesseract OCR (PSM {self.psm_mode}, {self.max_workers} workers)")

        source_stage = storage.stage("source")
        source_pages = source_stage.list_output_pages(extension="png")

        if len(source_pages) == 0:
            raise ValueError("No source pages found - cannot run tesseract stage")

        logger.info(f"Found {len(source_pages)} source pages")

    def run(
        self,
        storage: BookStorage,
        logger: PipelineLogger,
    ) -> Dict[str, Any]:
        if self.status_tracker.is_completed(storage, logger):
            return self.status_tracker.get_skip_response(storage, logger)

        status = self.get_status(storage, logger)
        remaining_pages = self.status_tracker.get_remaining_items(storage, logger)

        return process_batch(
            storage,
            logger,
            remaining_pages,
            self.psm_mode,
            self.max_workers
        )
