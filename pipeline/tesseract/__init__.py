import multiprocessing
from typing import Dict, Any

from infra.pipeline.base_stage import BaseStage
from infra.storage.book_storage import BookStorage
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

    def __init__(self, storage: BookStorage, psm_mode: int = 3, max_workers: int = None):
        super().__init__(storage)
        self.psm_mode = psm_mode
        self.max_workers = max_workers or multiprocessing.cpu_count()
        self.status_tracker = BatchBasedStatusTracker(
            storage=self.storage,
            logger=self.logger,
            stage_name=self.name,
            item_pattern="page_{:04d}.json"
        )

    def before(self) -> None:
        self.check_source_exists()

    def run(self) -> Dict[str, Any]:
        if self.status_tracker.is_completed():
            return self.status_tracker.get_skip_response()

        remaining_pages = self.status_tracker.get_remaining_items()

        return process_batch(
            self.storage,
            self.logger,
            remaining_pages,
            self.psm_mode,
            self.max_workers
        )
