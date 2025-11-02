"""
OCR Stage: Parallel provider execution with vision-based selection.

Architecture:
- All providers run in parallel per page (Tesseract PSM 3/4/6 by default)
- Vision LLM selects best provider output for low-agreement pages
- Multi-phase resume support with incremental checkpointing
"""

import multiprocessing
from typing import List, Dict, Any, Optional

from infra.pipeline.base_stage import BaseStage
from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger

from .schemas import OCRPageOutput, OCRPageReport
from .providers.schemas import OCRPageMetrics
from .providers import OCRProvider, TesseractProvider, OCRProviderConfig
from .status import OCRStatusTracker, OCRStageStatus
from .storage import OCRStageStorage


class OCRStage(BaseStage):
    name = "ocr"
    dependencies = ["source"]

    output_schema = OCRPageOutput
    checkpoint_schema = OCRPageMetrics
    report_schema = OCRPageReport
    self_validating = True

    def __init__(
        self,
        providers: Optional[List[OCRProvider]] = None,
        max_workers: Optional[int] = None,
    ):
        super().__init__()

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
        self.provider_ids = [p.config.name for p in self.providers]

        self.status_tracker = OCRStatusTracker(
            stage_name=self.name,
            provider_names=self.provider_ids
        )
        self.ocr_storage = OCRStageStorage(stage_name=self.name)

    def get_status(self, storage: BookStorage, logger: PipelineLogger) -> Dict[str, Any]:
        return self.status_tracker.get_status(storage)

    def before(self, storage: BookStorage, logger: PipelineLogger):
        logger.info(f"OCR with {len(self.providers)} providers:")
        for provider in self.providers:
            logger.info(f"  - {provider.provider_name}")
        logger.info(f"CPU workers: {self.max_workers}")

        source_stage = storage.stage("source")
        source_pages = source_stage.list_output_pages(extension="png")

        if len(source_pages) == 0:
            raise ValueError("No source pages found - cannot run OCR stage")

    def run(
        self,
        storage: BookStorage,
        logger: PipelineLogger,
    ) -> Dict[str, Any]:
        progress = self.get_status(storage, logger)
        total_pages = progress["total_pages"]
        status = progress["status"]

        logger.info(f"OCR Status: {status}")
        logger.info(f"Progress: {total_pages - len(progress['remaining_pages'])}/{total_pages} pages complete")

        # Phase 1: Parallel OCR extraction
        if status in [OCRStageStatus.NOT_STARTED.value, OCRStageStatus.RUNNING_OCR.value]:
            has_ocr_work = any(len(pages) > 0 for pages in progress["providers"].values())

            if has_ocr_work:
                logger.info("=== Phase 1: Parallel OCR Extraction ===")
                from .tools.parallel_ocr import run_parallel_ocr
                run_parallel_ocr(
                    storage, logger, self.ocr_storage,
                    self.providers, self.output_schema, total_pages,
                    self.max_workers, self.name
                )
                progress = self.get_status(storage, logger)

        # Phase 2a: Calculate provider agreement
        pages_needing_agreement = progress["selection"]["pages_needing_agreement"]
        if len(pages_needing_agreement) > 0:
            logger.info("=== Phase 2a: Calculate Provider Agreement ===")
            from .tools.agreement import calculate_agreements
            calculate_agreements(
                storage, logger, self.ocr_storage,
                self.providers, pages_needing_agreement, self.name
            )
            progress = self.get_status(storage, logger)

        # Phase 2b: Auto-select high agreement pages
        pages_for_auto_select = progress["selection"]["pages_for_auto_select"]
        if len(pages_for_auto_select) > 0:
            logger.info("=== Phase 2b: Auto-Select High Agreement Pages ===")
            from .tools.auto_selector import auto_select_pages
            auto_select_pages(
                storage, logger, self.ocr_storage,
                self.providers, pages_for_auto_select, self.name
            )
            progress = self.get_status(storage, logger)

        # Phase 2c: Vision-select low agreement pages
        pages_needing_vision = progress["selection"]["pages_needing_vision"]
        if len(pages_needing_vision) > 0:
            logger.info("=== Phase 2c: Vision-Select Low Agreement Pages ===")
            from .vision.selector import vision_select_pages
            vision_select_pages(
                storage, logger, self.ocr_storage,
                self.providers, pages_needing_vision, total_pages, self.name
            )
            progress = self.get_status(storage, logger)
        else:
            logger.info("No pages need vision selection (all pages have high agreement)")

        # Phase 3: Extract book metadata
        if len(progress["remaining_pages"]) == 0:
            needs_metadata = progress["metadata"]["needs_extraction"]
            if needs_metadata:
                logger.info("=== Phase 3: Extract Book Metadata ===")
                from .tools.metadata_extractor import extract_metadata
                extract_metadata(
                    storage, logger, self.ocr_storage, self.name
                )
                progress = self.get_status(storage, logger)

        # Phase 4: Generate report
        if len(progress["remaining_pages"]) == 0 and not progress["metadata"]["needs_extraction"]:
            needs_report = not progress["artifacts"]["report_exists"]
            if needs_report:
                logger.info("=== Phase 4: Generate Report ===")
                from .tools.report_generator import generate_report
                generate_report(
                    storage, logger, self.ocr_storage, self.report_schema, self.name
                )
                progress = self.get_status(storage, logger)

        completed_pages = total_pages - len(progress["remaining_pages"])
        total_cost = progress["metrics"]["total_cost_usd"]

        return {
            "pages_processed": completed_pages,
            "total_cost_usd": total_cost,
        }

