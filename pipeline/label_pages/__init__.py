"""
Label-Pages Stage: Vision-based page number extraction and block classification.

Architecture:
- Single-phase processing: Labeling → Report
- Uses LLMBatchProcessor for parallel vision-based labeling
- Dynamic per-page schemas constrain block count to match OCR
- Incremental checkpointing for resume support

Each page:
1. Load OCR data and source image
2. Generate page-specific schema (prevents LLM from adding/removing blocks)
3. Run vision-based labeling via LLM
4. Extract page numbers, classify page regions, classify block types
5. Save labeled output + checkpoint
"""

from typing import Dict, Any

from infra.pipeline.base_stage import BaseStage
from infra.storage.book_storage import BookStorage
from infra.storage.checkpoint import CheckpointManager
from infra.pipeline.logger import PipelineLogger

from .schemas import LabelPagesPageOutput, LabelPagesPageMetrics, LabelPagesPageReport
from .status import LabelPagesStatusTracker, LabelPagesStatus
from .storage import LabelPagesStageStorage


class LabelPagesStage(BaseStage):
    """
    Label-Pages Stage: Vision-based page number extraction and block classification.

    Reads: ocr/*.json (OCR outputs) + source/*.png (page images)
    Writes: label-pages/*.json (page numbers, regions, block classifications)

    Labeling philosophy:
    - Extract printed page numbers from page images (e.g., 'ix', '45')
    - Classify page regions (front matter, body, back matter, ToC)
    - Classify block types (chapter heading, body, footnote, etc.)
    - No text correction (that's handled in paragraph-correct stage)
    """

    name = "label-pages"
    dependencies = ["ocr", "source"]

    output_schema = LabelPagesPageOutput
    checkpoint_schema = LabelPagesPageMetrics
    report_schema = LabelPagesPageReport
    self_validating = True  # Single phase with internal progress tracking

    def __init__(
        self,
        model: str = None,
        max_workers: int = None,
        max_retries: int = 3,
    ):
        """
        Initialize Label-Pages stage.

        Args:
            model: Vision LLM model (default: Config.vision_model_primary)
            max_workers: Number of parallel workers (default: Config.max_workers)
            max_retries: Maximum retry attempts for failed pages (default: 3)
        """
        super().__init__()

        from infra.config import Config
        self.model = model or Config.vision_model_primary
        self.max_workers = max_workers or Config.max_workers
        self.max_retries = max_retries

        # Create status tracker and storage manager
        self.status_tracker = LabelPagesStatusTracker(stage_name=self.name)
        self.stage_storage = LabelPagesStageStorage(stage_name=self.name)

    def get_progress(
        self,
        storage: BookStorage,
        checkpoint: CheckpointManager,
        logger: PipelineLogger
    ) -> Dict[str, Any]:
        """Delegate to status tracker for progress calculation."""
        return self.status_tracker.get_progress(storage, checkpoint, logger)

    def before(
        self,
        storage: BookStorage,
        checkpoint: CheckpointManager,
        logger: PipelineLogger
    ):
        """Pre-run validation: ensure OCR stage completed."""
        logger.info(f"Label-Pages with {self.model}")
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

        # Verify OCR is completed
        if ocr_progress['status'] != 'completed':
            raise RuntimeError(
                f"OCR stage status is '{ocr_progress['status']}', not 'completed'. "
                f"Run OCR stage to completion first."
            )

        # Log OCR completion info
        logger.info(f"OCR completed: {ocr_progress['total_pages']} pages ready for labeling")

    def run(
        self,
        storage: BookStorage,
        checkpoint: CheckpointManager,
        logger: PipelineLogger,
    ) -> Dict[str, Any]:
        """
        Run label-pages with status-based resume.

        Uses progress status to determine what work needs to be done,
        enabling efficient resume from any interruption point.

        Returns:
            Stats dict with pages_processed, total_cost_usd, etc.
        """
        # Get current progress to determine what needs to be done
        progress = self.get_progress(storage, checkpoint, logger)
        total_pages = progress["total_pages"]
        status = progress["status"]

        logger.info(f"Status: {status}")
        logger.info(f"Total pages: {total_pages}")
        logger.info(f"Remaining pages: {len(progress['remaining_pages'])}")
        logger.info(f"Progress: {total_pages - len(progress['remaining_pages'])}/{total_pages} pages complete")

        # Phase 1: Label remaining pages
        if status in [LabelPagesStatus.NOT_STARTED.value, LabelPagesStatus.LABELING.value]:
            remaining_pages = progress["remaining_pages"]

            if len(remaining_pages) > 0:
                logger.info("=== Phase 1: Vision-Based Labeling ===")
                checkpoint.set_phase(LabelPagesStatus.LABELING.value, f"0/{total_pages} pages")

                from .tools.processor import label_pages
                label_pages(
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

                # Refresh progress after labeling
                progress = self.get_progress(storage, checkpoint, logger)

        # Phase 2: Generate report from checkpoint metrics
        # Check disk state directly, not remaining_pages (report can be regenerated)
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

        # Mark stage as completed if all phases done
        all_complete = (
            len(progress["remaining_pages"]) == 0
            and progress["artifacts"]["report_exists"]
        )
        if all_complete:
            checkpoint.set_phase(LabelPagesStatus.COMPLETED.value)

        # Calculate final stats
        completed_pages = total_pages - len(progress["remaining_pages"])
        total_cost = progress["metrics"]["total_cost_usd"]

        return {
            "pages_processed": completed_pages,
            "total_cost_usd": total_cost,
        }
