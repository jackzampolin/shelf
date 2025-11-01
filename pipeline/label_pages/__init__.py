from typing import Dict, Any

from infra.pipeline.base_stage import BaseStage
from infra.storage.book_storage import BookStorage
from infra.storage.checkpoint import CheckpointManager
from infra.pipeline.logger import PipelineLogger

from .schemas import LabelPagesPageOutput, LabelPagesPageMetrics, LabelPagesPageReport
from .status import LabelPagesStatusTracker, LabelPagesStatus
from .storage import LabelPagesStageStorage


class LabelPagesStage(BaseStage):

    name = "label-pages"
    dependencies = ["ocr", "source"]

    output_schema = LabelPagesPageOutput
    checkpoint_schema = LabelPagesPageMetrics
    report_schema = LabelPagesPageReport
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

        self.status_tracker = LabelPagesStatusTracker(stage_name=self.name)
        self.stage_storage = LabelPagesStageStorage(stage_name=self.name)

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
        logger.info(f"Label-Pages with {self.model}")
        logger.info(f"Max workers: {self.max_workers}")

        from pipeline.ocr import OCRStage
        ocr_stage = OCRStage()

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

        logger.info(f"OCR completed: {ocr_progress['total_pages']} pages ready for labeling")

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

        # Phase 1: Two-stage vision processing
        if status in [LabelPagesStatus.NOT_STARTED.value, LabelPagesStatus.LABELING.value]:
            # Phase 1a: Stage 1 - Structural analysis (3-image context)
            stage1_completed = self.stage_storage.list_stage1_completed_pages(storage)
            stage1_remaining = [p for p in range(1, total_pages + 1) if p not in stage1_completed]

            if len(stage1_remaining) > 0:
                logger.info("=== Phase 1a: Stage 1 - Structural Analysis (3 images) ===")
                logger.info(f"Remaining: {len(stage1_remaining)}/{total_pages} pages")
                checkpoint.set_phase(LabelPagesStatus.LABELING.value, f"Stage 1: 0/{total_pages} pages")

                from .tools.processor_stage1 import process_stage1
                process_stage1(
                    storage=storage,
                    checkpoint=checkpoint,
                    logger=logger,
                    stage_storage=self.stage_storage,
                    model=self.model,
                    max_workers=self.max_workers,
                    max_retries=self.max_retries,
                    remaining_pages=stage1_remaining,
                    total_pages=total_pages,
                )

            # Phase 1b: Stage 2 - Block classification (1 image + Stage 1 context)
            remaining_pages = progress["remaining_pages"]

            if len(remaining_pages) > 0:
                logger.info("=== Phase 1b: Stage 2 - Block Classification (with Stage 1 context) ===")
                logger.info(f"Remaining: {len(remaining_pages)}/{total_pages} pages")
                checkpoint.set_phase(LabelPagesStatus.LABELING.value, f"Stage 2: 0/{total_pages} pages")

                from .tools.processor_stage2 import process_stage2
                process_stage2(
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

        # Phase 2: Generate classification report (CSV with page numbers and block types)
        if not progress["artifacts"]["report_exists"]:
                logger.info("=== Phase 2: Generate Report ===")
                checkpoint.set_phase(LabelPagesStatus.GENERATING_REPORT.value)

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
            checkpoint.set_phase(LabelPagesStatus.COMPLETED.value)

        completed_pages = total_pages - len(progress["remaining_pages"])
        total_cost = progress["metrics"]["total_cost_usd"]

        return {
            "pages_processed": completed_pages,
            "total_cost_usd": total_cost,
        }
