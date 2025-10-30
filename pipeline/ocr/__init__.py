"""
OCR Stage: Parallel OCR with unified page iteration.

Architecture:
- All PSM modes run in parallel per page (not sequentially)
- Vision selection queued immediately after PSM completion
- Simple checkpointing with multi-phase resume support
- Amortizes LLM latency over Tesseract CPU cycles
- Pluggable OCR providers for easy experimentation
"""

import multiprocessing
from typing import List, Dict, Any, Optional

from infra.pipeline.base_stage import BaseStage
from infra.storage.book_storage import BookStorage
from infra.storage.checkpoint import CheckpointManager
from infra.pipeline.logger import PipelineLogger

from .schemas import OCRPageOutput, OCRPageReport
from .providers.schemas import OCRPageMetrics
from .providers import OCRProvider, TesseractProvider, OCRProviderConfig
from .status import OCRStatusTracker, OCRStageStatus
from .storage import OCRStageStorage


class OCRStage(BaseStage):
    """
    OCR Stage: Unified page iteration with parallel provider execution.

    Architecture:
    - Tesseract Pool (ProcessPoolExecutor): All providers run in parallel per page
    - Vision Pool (ThreadPoolExecutor): Vision selection queued as PSMs complete
    - Pipeline: Vision processes page N-1 while Tesseract processes page N

    Each page:
    1. Run all OCR providers in parallel (e.g., PSM3, PSM4, PSM6)
    2. Queue vision selection to choose best provider output
    3. Save selected result + checkpoint
    """

    name = "ocr"
    dependencies = ["source"]

    output_schema = OCRPageOutput
    checkpoint_schema = OCRPageMetrics
    report_schema = OCRPageReport
    self_validating = True  # Stage manages its own multi-phase completion status

    def __init__(
        self,
        providers: Optional[List[OCRProvider]] = None,
        max_workers: Optional[int] = None,
    ):
        """
        Args:
            providers: List of OCR providers to run in parallel.
                      Default: [TesseractProvider(psm=3/4/6)]
            max_workers: CPU workers for parallel OCR processing.
                        Default: cpu_count()
        """
        super().__init__()

        # Default to traditional Tesseract PSM modes
        if providers is None:
            self.providers = [
                TesseractProvider(
                    OCRProviderConfig(name=f"tesseract-psm{psm}"),
                    psm_mode=psm,
                )
                for psm in [3, 4, 6]
            ]
        else:
            self.providers = providers

        self.max_workers = max_workers or multiprocessing.cpu_count()

        # Extract provider identifiers for checkpoint tracking
        self.provider_ids = [p.config.name for p in self.providers]

        # Create status tracker and storage manager
        self.status_tracker = OCRStatusTracker(
            stage_name=self.name,
            provider_names=self.provider_ids
        )
        self.ocr_storage = OCRStageStorage(stage_name=self.name)

    def get_progress(self, storage: BookStorage, checkpoint: CheckpointManager, logger: PipelineLogger) -> Dict[str, Any]:
        """Delegate to status tracker for progress calculation."""
        return self.status_tracker.get_progress(storage, checkpoint, logger)

    def before(self, storage: BookStorage, checkpoint: CheckpointManager, logger: PipelineLogger):
        """Pre-run validation and initialization."""
        logger.info(f"OCR with {len(self.providers)} providers:")
        for provider in self.providers:
            logger.info(f"  - {provider.provider_name}")
        logger.info(f"CPU workers: {self.max_workers}")

        # Validate source files exist
        source_stage = storage.stage("source")
        source_pages = source_stage.list_output_pages(extension="png")

        if len(source_pages) == 0:
            raise ValueError("No source pages found - cannot run OCR stage")

    def run(
        self,
        storage: BookStorage,
        checkpoint: CheckpointManager,
        logger: PipelineLogger,
    ) -> Dict[str, Any]:
        """
        Run OCR with status-based resume.

        Uses progress status to determine what work needs to be done,
        enabling efficient resume from any interruption point.

        Returns:
            Stats dict with pages_processed, total_cost_usd, etc.
        """
        # Get current progress to determine what needs to be done
        progress = self.get_progress(storage, checkpoint, logger)
        total_pages = progress["total_pages"]
        status = progress["status"]

        logger.info(f"OCR Status: {status}")
        logger.info(f"Progress: {total_pages - len(progress['remaining_pages'])}/{total_pages} pages complete")

        # Phase 1: Run OCR for incomplete providers
        if status in [OCRStageStatus.NOT_STARTED.value, OCRStageStatus.RUNNING_OCR.value]:
            # Check if any provider work remains
            has_ocr_work = any(len(pages) > 0 for pages in progress["providers"].values())

            if has_ocr_work:
                logger.info("=== Phase 1: Parallel OCR Extraction ===")
                checkpoint.set_phase(OCRStageStatus.RUNNING_OCR.value, f"0/{total_pages} pages")
                from .tools.parallel_ocr import run_parallel_ocr
                run_parallel_ocr(
                    storage, checkpoint, logger, self.ocr_storage,
                    self.providers, self.output_schema, total_pages,
                    self.max_workers, self.name
                )
                # Refresh progress after OCR
                progress = self.get_progress(storage, checkpoint, logger)

        # Phase 2: Provider selection - broken into 3 sub-phases for resume
        # Each sub-phase writes incrementally for seamless cancel/resume

        # Phase 2a: Calculate agreement
        pages_needing_agreement = progress["selection"]["pages_needing_agreement"]
        if len(pages_needing_agreement) > 0:
            logger.info("=== Phase 2a: Calculate Provider Agreement ===")
            checkpoint.set_phase(OCRStageStatus.CALCULATING_AGREEMENT.value)
            from .tools.agreement import calculate_agreements
            calculate_agreements(
                storage, checkpoint, logger, self.ocr_storage,
                self.providers, pages_needing_agreement
            )
            progress = self.get_progress(storage, checkpoint, logger)

        # Phase 2b: Auto-select high agreement pages
        pages_for_auto_select = progress["selection"]["pages_for_auto_select"]
        if len(pages_for_auto_select) > 0:
            logger.info("=== Phase 2b: Auto-Select High Agreement Pages ===")
            checkpoint.set_phase(OCRStageStatus.AUTO_SELECTING.value)
            from .tools.auto_selector import auto_select_pages
            auto_select_pages(
                storage, checkpoint, logger, self.ocr_storage,
                self.providers, pages_for_auto_select
            )
            progress = self.get_progress(storage, checkpoint, logger)

        # Phase 2c: Vision-select low agreement pages
        pages_needing_vision = progress["selection"]["pages_needing_vision"]
        if len(pages_needing_vision) > 0:
            logger.info("=== Phase 2c: Vision-Select Low Agreement Pages ===")
            checkpoint.set_phase(OCRStageStatus.RUNNING_VISION.value)
            from .vision.selector import vision_select_pages
            vision_select_pages(
                storage, checkpoint, logger, self.ocr_storage,
                self.providers, pages_needing_vision, total_pages
            )
            progress = self.get_progress(storage, checkpoint, logger)
        else:
            logger.info("No pages need vision selection (all pages have high agreement)")

        # Phase 3: Extract book metadata from first 15 pages
        if len(progress["remaining_pages"]) == 0:  # All pages selected
            needs_metadata = progress["metadata"]["needs_extraction"]
            if needs_metadata:
                logger.info("=== Phase 3: Extract Book Metadata ===")
                checkpoint.set_phase(OCRStageStatus.EXTRACTING_METADATA.value)
                from .tools.metadata_extractor import extract_metadata
                extract_metadata(
                    storage, checkpoint, logger, self.ocr_storage
                )
                progress = self.get_progress(storage, checkpoint, logger)

        # Phase 4: Generate report.csv from checkpoint metrics
        if len(progress["remaining_pages"]) == 0 and not progress["metadata"]["needs_extraction"]:
            needs_report = not progress["artifacts"]["report_exists"]
            if needs_report:
                logger.info("=== Phase 4: Generate Report ===")
                checkpoint.set_phase(OCRStageStatus.GENERATING_REPORT.value)
                from .tools.report_generator import generate_report
                generate_report(
                    storage, checkpoint, logger, self.ocr_storage, self.report_schema
                )
                progress = self.get_progress(storage, checkpoint, logger)

        # Mark stage as completed if all phases done
        all_complete = (
            len(progress["remaining_pages"]) == 0
            and not progress["metadata"]["needs_extraction"]
            and progress["artifacts"]["report_exists"]
        )
        if all_complete:
            checkpoint.set_phase(OCRStageStatus.COMPLETED.value)

        # Calculate final stats
        completed_pages = total_pages - len(progress["remaining_pages"])
        total_cost = progress["metrics"]["total_cost_usd"]

        return {
            "pages_processed": completed_pages,
            "total_cost_usd": total_cost,
        }

