"""
Paragraph-Correct Stage: Vision-based OCR error correction.

Architecture:
- Single-phase processing: Correction → Report
- Uses LLMBatchProcessor for parallel vision-based correction
- Dynamic per-page schemas constrain block/paragraph structure
- Incremental checkpointing for resume support

Each page:
1. Load OCR data and source image
2. Generate page-specific schema (prevents LLM from adding/removing blocks)
3. Run vision-based correction via LLM
4. Calculate quality metrics (similarity, confidence)
5. Save corrected output + checkpoint
"""

from typing import Dict, Any, Optional
from pathlib import Path

from infra.pipeline.base_stage import BaseStage
from infra.storage.book_storage import BookStorage
from infra.storage.checkpoint import CheckpointManager
from infra.pipeline.logger import PipelineLogger

from .schemas import ParagraphCorrectPageOutput, ParagraphCorrectPageMetrics, ParagraphCorrectPageReport
from .status import ParagraphCorrectStatusTracker, ParagraphCorrectStatus
from .storage import ParagraphCorrectStageStorage


class ParagraphCorrectStage(BaseStage):
    """
    Paragraph-Correct Stage: Vision-based OCR error correction.

    Reads: ocr/*.json (OCR outputs) + source/*.png (page images)
    Writes: paragraph-correct/*.json (corrections with confidence scores)

    Correction philosophy:
    - Fix OCR character-reading errors only (not authorial style)
    - Most common: line-break hyphens, character substitutions, ligatures
    - Preserve historical spellings and legitimate compound words
    - Return full corrected paragraph text (not diffs)
    """

    name = "paragraph-correct"
    dependencies = ["ocr", "source"]

    output_schema = ParagraphCorrectPageOutput
    checkpoint_schema = ParagraphCorrectPageMetrics
    report_schema = ParagraphCorrectPageReport
    self_validating = True  # Single phase with internal progress tracking

    def __init__(
        self,
        model: str = None,
        max_workers: int = None,
        max_retries: int = 3,
    ):
        """
        Initialize Paragraph-Correct stage.

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
        self.status_tracker = ParagraphCorrectStatusTracker(stage_name=self.name)
        self.stage_storage = ParagraphCorrectStageStorage(stage_name=self.name)

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

        # Verify OCR is completed
        if ocr_progress['status'] != 'completed':
            raise RuntimeError(
                f"OCR stage status is '{ocr_progress['status']}', not 'completed'. "
                f"Run OCR stage to completion first."
            )

        # Log OCR completion info
        logger.info(f"OCR completed: {ocr_progress['total_pages']} pages ready for correction")

    def run(
        self,
        storage: BookStorage,
        checkpoint: CheckpointManager,
        logger: PipelineLogger,
    ) -> Dict[str, Any]:
        """
        Run paragraph correction with status-based resume.

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

        # Phase 1: Correct remaining pages
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

                # Refresh progress after correction
                progress = self.get_progress(storage, checkpoint, logger)

        # Phase 2: Generate report from checkpoint metrics
        # Check disk state directly, not remaining_pages (report can be regenerated)
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

        # Mark stage as completed if all phases done
        all_complete = (
            len(progress["remaining_pages"]) == 0
            and progress["artifacts"]["report_exists"]
        )
        if all_complete:
            checkpoint.set_phase(ParagraphCorrectStatus.COMPLETED.value)

        # Calculate final stats
        completed_pages = total_pages - len(progress["remaining_pages"])
        total_cost = progress["metrics"]["total_cost_usd"]

        return {
            "pages_processed": completed_pages,
            "total_cost_usd": total_cost,
        }
