from typing import Dict, Any

from infra.pipeline.base_stage import BaseStage
from infra.storage.book_storage import BookStorage
from infra.storage.checkpoint import CheckpointManager
from infra.pipeline.logger import PipelineLogger

from .schemas import ParagraphCorrectPageOutput, ParagraphCorrectPageMetrics, ParagraphCorrectPageReport
from .status import ParagraphCorrectStatusTracker, ParagraphCorrectStatus
from .storage import ParagraphCorrectStageStorage


class ParagraphCorrectStage(BaseStage):

    name = "paragraph-correct"
    dependencies = ["ocr", "source"]

    output_schema = ParagraphCorrectPageOutput
    checkpoint_schema = ParagraphCorrectPageMetrics
    report_schema = ParagraphCorrectPageReport
    self_validating = True

    def __init__(
        self,
        model: str = None,
        max_workers: int = None,
        max_retries: int = 3,
    ):
        super().__init__()

        from infra.config import Config
        self.model = model or Config.vision_model_primary
        self.max_workers = max_workers or Config.max_workers
        self.max_retries = max_retries

        # Create status tracker and storage manager
        self.status_tracker = ParagraphCorrectStatusTracker(stage_name=self.name)
        self.stage_storage = ParagraphCorrectStageStorage(stage_name=self.name)

    def get_progress(
        self,
        storage: BookStorage,
        checkpoint: CheckpointManager,
        logger: PipelineLogger
    ) -> Dict[str, Any]:
        return self.status_tracker.get_progress(storage, checkpoint, logger)

    def before(
        self,
        storage: BookStorage,
        checkpoint: CheckpointManager,
        logger: PipelineLogger
    ):
        logger.info(f"Paragraph-Correct with {self.model}")
        logger.info(f"Max workers: {self.max_workers}")

        # Check OCR stage status
        from pipeline.ocr import OCRStage
        ocr_stage = OCRStage()

        # Get OCR checkpoint for status check
        ocr_checkpoint = CheckpointManager(
            scan_id=storage.scan_id,
            stage='ocr'
        )

        ocr_progress = ocr_stage.get_progress(storage, ocr_checkpoint, logger)

        if ocr_progress['status'] != 'completed':
            raise RuntimeError(
                f"OCR stage status is '{ocr_progress['status']}', not 'completed'. "
                f"Run OCR stage to completion first."
            )

        logger.info(f"OCR completed: {ocr_progress['total_pages']} pages ready for correction")

    def run(
        self,
        storage: BookStorage,
        checkpoint: CheckpointManager,
        logger: PipelineLogger,
    ) -> Dict[str, Any]:

        progress = self.get_progress(storage, checkpoint, logger)
        total_pages = progress["total_pages"]
        status = progress["status"]

        logger.info(f"Status: {status}")
        logger.info(f"Total pages: {total_pages}")
        logger.info(f"Remaining pages: {len(progress['remaining_pages'])}")
        logger.info(f"Progress: {total_pages - len(progress['remaining_pages'])}/{total_pages} pages complete")

        # Phase 1: Vision-based correction (parallel processing)
        if status in [ParagraphCorrectStatus.NOT_STARTED.value, ParagraphCorrectStatus.CORRECTING.value]:
            remaining_pages = progress["remaining_pages"]

            if len(remaining_pages) > 0:
                logger.info("=== Phase 1: Vision-Based Correction ===")
                checkpoint.set_phase(ParagraphCorrectStatus.CORRECTING.value, f"0/{total_pages} pages")

                from .tools.processor import correct_pages
                correct_pages(
                    storage=storage,
                    checkpoint=checkpoint,
                    logger=logger,
                    stage_storage=self.stage_storage,
                    model=self.model,
                    max_workers=self.max_workers,
                    max_retries=self.max_retries,
                    remaining_pages=remaining_pages,
                    total_pages=total_pages,
                    output_schema=self.output_schema,
                )

                progress = self.get_progress(storage, checkpoint, logger)

        # Phase 2: Generate quality report (CSV with similarity metrics)
        if not progress["artifacts"]["report_exists"]:
                logger.info("=== Phase 2: Generate Report ===")
                checkpoint.set_phase(ParagraphCorrectStatus.GENERATING_REPORT.value)

                from .tools.report_generator import generate_report
                generate_report(
                    storage=storage,
                    checkpoint=checkpoint,
                    logger=logger,
                    stage_storage=self.stage_storage,
                    report_schema=self.report_schema,
                )

                progress = self.get_progress(storage, checkpoint, logger)

        all_complete = (
            len(progress["remaining_pages"]) == 0
            and progress["artifacts"]["report_exists"]
        )
        if all_complete:
            checkpoint.set_phase(ParagraphCorrectStatus.COMPLETED.value)

        completed_pages = total_pages - len(progress["remaining_pages"])
        total_cost = progress["metrics"]["total_cost_usd"]

        return {
            "pages_processed": completed_pages,
            "total_cost_usd": total_cost,
        }
