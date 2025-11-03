from typing import Dict, Any

from infra.pipeline.base_stage import BaseStage
from infra.storage.book_storage import BookStorage
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

    def get_status(
        self,
        storage: BookStorage,
        logger: PipelineLogger
    ) -> Dict[str, Any]:
        return self.status_tracker.get_status(storage)

    def pretty_print_status(self, status: Dict[str, Any]) -> str:
        """Return formatted label-pages status with two-stage progress and classification details."""
        lines = [super().pretty_print_status(status)]

        # Label-pages specific: two-stage processing
        stage1_remaining = len(status.get('stage1_remaining', []))
        stage2_remaining = len(status.get('stage2_remaining', []))
        total = status.get('total_pages', 0)

        if stage1_remaining < total or stage2_remaining < total:
            stage1_complete = total - stage1_remaining
            stage2_complete = total - stage2_remaining
            lines.append(f"   Stage 1: {stage1_complete}/{total} ({stage1_remaining} remaining)")
            lines.append(f"   Stage 2: {stage2_complete}/{total} ({stage2_remaining} remaining)")

        # Label-pages specific: classification metrics
        metrics = status.get('metrics', {})
        total_blocks = metrics.get('total_blocks_classified', 0)
        avg_conf = metrics.get('avg_classification_confidence', 0.0)
        pages_with_numbers = metrics.get('pages_with_numbers', 0)
        pages_with_regions = metrics.get('pages_with_regions', 0)

        if total_blocks > 0:
            lines.append(f"   Blocks Classified: {total_blocks}")
        if avg_conf > 0:
            lines.append(f"   Avg Confidence: {avg_conf:.2%}")
        if pages_with_numbers > 0:
            lines.append(f"   Pages w/ Numbers: {pages_with_numbers}")
        if pages_with_regions > 0:
            lines.append(f"   Pages w/ Regions: {pages_with_regions}")

        # Label-pages specific: stage costs breakdown
        stage1_cost = metrics.get('stage1_cost_usd', 0)
        stage2_cost = metrics.get('stage2_cost_usd', 0)
        if stage1_cost > 0 or stage2_cost > 0:
            lines.append(f"   Stage 1 Cost: ${stage1_cost:.4f}")
            lines.append(f"   Stage 2 Cost: ${stage2_cost:.4f}")

        return '\n'.join(lines)

    def before(
        self,
        storage: BookStorage,
        logger: PipelineLogger
    ):
        logger.info(f"Label-Pages with {self.model}")
        logger.info(f"Max workers: {self.max_workers}")

        from pipeline.ocr import OCRStage
        ocr_stage = OCRStage()

        ocr_progress = ocr_stage.get_status(storage, logger)

        if ocr_progress['status'] != 'completed':
            raise RuntimeError(
                f"OCR stage status is '{ocr_progress['status']}', not 'completed'. "
                f"Run OCR stage to completion first."
            )

        logger.info(f"OCR completed: {ocr_progress['total_pages']} pages ready for labeling")

    def run(
        self,
        storage: BookStorage,
        logger: PipelineLogger,
    ) -> Dict[str, Any]:

        progress = self.get_status(storage, logger)
        total_pages = progress["total_pages"]
        status = progress["status"]

        logger.info(f"Status: {status}")
        logger.info(f"Total pages: {total_pages}")
        logger.info(f"Remaining pages: {len(progress['remaining_pages'])}")
        logger.info(f"Progress: {total_pages - len(progress['remaining_pages'])}/{total_pages} pages complete")

        # Phase 1: Two-stage vision processing
        if status in [LabelPagesStatus.NOT_STARTED.value, LabelPagesStatus.LABELING_STAGE1.value, LabelPagesStatus.LABELING_STAGE2.value]:
            from infra.llm.batch_processor import LLMBatchProcessor, LLMBatchConfig, batch_process_with_preparation
            from .stage1.request_builder import prepare_stage1_request
            from .stage1.result_handler import create_stage1_handler
            from .stage2.request_builder import prepare_stage2_request
            from .stage2.result_handler import create_stage2_handler

            # Phase 1a: Stage 1 - Structural analysis (3-image context)
            stage1_completed = self.stage_storage.list_stage1_completed_pages(storage)
            stage1_remaining = [p for p in range(1, total_pages + 1) if p not in stage1_completed]

            if len(stage1_remaining) > 0:
                logger.info("=== Phase 1a: Stage 1 - Structural Analysis (3 images) ===")
                logger.info(f"Remaining: {len(stage1_remaining)}/{total_pages} pages")

                # Setup processor and handler
                stage_storage_dir = storage.stage(self.stage_storage.stage_name)
                log_dir = stage_storage_dir.output_dir / "logs" / "stage1"
                config = LLMBatchConfig(model=self.model, max_workers=self.max_workers, max_retries=self.max_retries)
                processor = LLMBatchProcessor(
                    logger=logger,
                    log_dir=log_dir,
                    config=config,
                    metrics_manager=stage_storage_dir.metrics_manager,
                )
                handler = create_stage1_handler(storage, self.stage_storage, logger, self.name)

                # Process batch
                stage1_stats = batch_process_with_preparation(
                    stage_name="Stage 1",
                    pages=stage1_remaining,
                    request_builder=prepare_stage1_request,
                    result_handler=handler,
                    processor=processor,
                    logger=logger,
                    storage=storage,
                    model=self.model,
                    total_pages=total_pages,
                )

                # Store actual runtime for stage 1
                if stage1_stats.get("elapsed_seconds"):
                    stage_storage_dir.metrics_manager.record(
                        key="stage_runtime",
                        time_seconds=stage1_stats["elapsed_seconds"],
                        accumulate=True
                    )

            # Phase 1b: Stage 2 - Block classification (1 image + Stage 1 context)
            remaining_pages = progress["remaining_pages"]

            if len(remaining_pages) > 0:
                logger.info("=== Phase 1b: Stage 2 - Block Classification (with Stage 1 context) ===")
                logger.info(f"Remaining: {len(remaining_pages)}/{total_pages} pages")

                # Collect OCR pages for Stage 2 handler
                ocr_pages = {}
                from pipeline.ocr.storage import OCRStageStorage
                from pipeline.ocr.schemas import OCRPageOutput
                ocr_storage = OCRStageStorage(stage_name='ocr')
                for page_num in remaining_pages:
                    ocr_data = ocr_storage.load_selected_page(storage, page_num, include_line_word_data=False)
                    if ocr_data:
                        ocr_pages[page_num] = OCRPageOutput(**ocr_data)

                # Setup processor and handler
                log_dir = stage_storage_dir.output_dir / "logs" / "stage2"
                config = LLMBatchConfig(model=self.model, max_workers=self.max_workers, max_retries=self.max_retries)
                processor = LLMBatchProcessor(
                    logger=logger,
                    log_dir=log_dir,
                    config=config,
                    metrics_manager=stage_storage_dir.metrics_manager,
                )
                handler = create_stage2_handler(storage, self.stage_storage, logger, self.model, self.output_schema, ocr_pages, self.name)

                # Process batch
                stage2_stats = batch_process_with_preparation(
                    stage_name="Stage 2",
                    pages=remaining_pages,
                    request_builder=prepare_stage2_request,
                    result_handler=handler,
                    processor=processor,
                    logger=logger,
                    storage=storage,
                    model=self.model,
                    total_pages=total_pages,
                    stage1_results=None,  # Loaded inside prepare_stage2_request
                )

                # Store actual runtime for stage 2
                if stage2_stats.get("elapsed_seconds"):
                    stage_storage_dir.metrics_manager.record(
                        key="stage_runtime",
                        time_seconds=stage2_stats["elapsed_seconds"],
                        accumulate=True
                    )

                progress = self.get_status(storage, logger)

        # Phase 2: Generate classification report (CSV with page numbers and block types)
        if not progress["artifacts"]["report_exists"]:
                logger.info("=== Phase 2: Generate Report ===")

                from .tools.report_generator import generate_report
                generate_report(
                    storage=storage,
                    logger=logger,
                    stage_storage=self.stage_storage,
                    report_schema=self.report_schema,
                    stage_name=self.name,
                )

                progress = self.get_status(storage, logger)

        completed_pages = total_pages - len(progress["remaining_pages"])
        total_cost = progress["metrics"]["total_cost_usd"]

        return {
            "pages_processed": completed_pages,
            "total_cost_usd": total_cost,
        }
