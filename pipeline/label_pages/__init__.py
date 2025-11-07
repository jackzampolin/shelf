from typing import Dict, Any

from infra.config import Config
from infra.pipeline.base_stage import BaseStage
from infra.storage.book_storage import BookStorage
from infra.pipeline.status import BatchBasedStatusTracker, MultiPhaseStatusTracker
from pipeline.ocr_pages import OcrPagesStage
from .tools.report_generator import generate_report
from .batch.processor import process_pages

from .schemas import LabelPagesPageOutput, LabelPagesPageReport


class LabelPagesStage(BaseStage):

    name = "label-pages"
    dependencies = ["ocr-pages", "source"]

    output_schema = LabelPagesPageOutput
    report_schema = LabelPagesPageReport
    self_validating = True

    def __init__(
        self,
        storage: BookStorage,
        model: str = None,
        max_workers: int = None,
        max_retries: int = 3,
    ):
        super().__init__(storage)

        self.model = model or Config.vision_model_primary
        self.max_workers = max_workers or Config.max_workers
        self.max_retries = max_retries

        # Two-phase status tracking: process pages + generate report
        self.page_tracker = BatchBasedStatusTracker(
            storage=self.storage,
            logger=self.logger,
            stage_name=self.name,
            item_pattern="page_{:04d}.json"
        )

        self.status_tracker = MultiPhaseStatusTracker(
            storage=self.storage,
            logger=self.logger,
            stage_name=self.name,
            phases=[
                {"name": "process_pages", "tracker": self.page_tracker},
                {"name": "generate_report", "artifact": "report.csv"}
            ]
        )

    def before(self) -> None:
        self.check_source_exists()

        ocr_pages_stage = OcrPagesStage(self.storage)
        self.check_dependency_completed(ocr_pages_stage)

    def run(self) -> Dict[str, Any]:
        if self.status_tracker.is_completed():
            return self.status_tracker.get_skip_response()

        # Phase 1: Process pages
        remaining_pages = self.page_tracker.get_remaining_items()
        if remaining_pages:
            process_pages(
                storage=self.storage,
                logger=self.logger,
                stage_name=self.name,
                output_schema=self.output_schema,
                remaining_pages=remaining_pages,
                model=self.model,
                max_workers=self.max_workers,
                max_retries=self.max_retries
            )

        # Phase 2: Generate report
        report_path = self.stage_storage.output_dir / "report.csv"
        if not report_path.exists():
            generate_report(
                storage=self.storage,
                logger=self.logger,
                report_schema=self.report_schema,
                stage_name=self.name,
            )

        return {"status": "success"}
