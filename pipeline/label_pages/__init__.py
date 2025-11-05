from typing import Dict, Any

from infra.pipeline.base_stage import BaseStage
from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger

from .schemas import LabelPagesPageOutput, LabelPagesPageReport
from .status import LabelPagesStatusTracker, LabelPagesStatus
from .storage import LabelPagesStageStorage


class LabelPagesStage(BaseStage):

    name = "label-pages"
    dependencies = ["tesseract", "source"]

    output_schema = LabelPagesPageOutput
    checkpoint_schema = None  # No checkpoints needed (single-stage)
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
        """Return formatted label-pages status."""
        lines = []

        stage_status = status.get('status', 'unknown')
        lines.append(f"   Status: {stage_status}")

        completed = status.get('completed_pages', 0)
        total = status.get('total_pages', 0)
        if total > 0:
            lines.append(f"   Pages:  {completed}/{total} completed")

        metrics = status.get('metrics', {})
        if metrics.get('total_cost_usd', 0) > 0:
            lines.append(f"   Cost:   ${metrics['total_cost_usd']:.4f}")
        if metrics.get('stage_runtime_seconds', 0) > 0:
            mins = metrics['stage_runtime_seconds'] / 60
            lines.append(f"   Time:   {mins:.1f}m")

        return '\n'.join(lines)

    def before(
        self,
        storage: BookStorage,
        logger: PipelineLogger
    ):
        logger.info(f"Label-Pages with {self.model}")
        logger.info(f"Max workers: {self.max_workers}")

        from pipeline.tesseract import TesseractStage
        tesseract_stage = TesseractStage()

        tesseract_progress = tesseract_stage.get_status(storage, logger)

        if tesseract_progress['status'] != 'completed':
            raise RuntimeError(
                f"Tesseract stage status is '{tesseract_progress['status']}', not 'completed'. "
                f"Run tesseract stage to completion first."
            )

        logger.info(f"Tesseract completed: {tesseract_progress['total_pages']} pages ready for labeling")

    def run(
        self,
        storage: BookStorage,
        logger: PipelineLogger,
    ) -> Dict[str, Any]:
        import time
        start_time = time.time()

        progress = self.get_status(storage, logger)
        total_pages = progress["total_pages"]
        remaining_pages = progress["remaining_pages"]
        status = progress["status"]

        logger.info(f"Status: {status}")
        logger.info(f"Total pages: {total_pages}")
        logger.info(f"Remaining pages: {len(remaining_pages)}")
        logger.info(f"Progress: {total_pages - len(remaining_pages)}/{total_pages} pages complete")

        if progress["status"] == LabelPagesStatus.COMPLETED.value:
            logger.info("Label-pages already completed (skipping)")
            return {
                "status": "skipped",
                "reason": "already completed",
                "pages_processed": total_pages - len(remaining_pages)
            }

        if len(remaining_pages) == 0:
            logger.info("No pages remaining to process")
            return {
                "status": "success",
                "pages_processed": 0
            }

        # Single-stage vision processing: Structural analysis with 3-image context
        logger.info(f"=== Label-Pages: Structural Analysis (3 images per page) ===")
        logger.info(f"Remaining: {len(remaining_pages)}/{total_pages} pages")

        from infra.llm.batch_processor import LLMBatchProcessor, LLMBatchConfig, batch_process_with_preparation
        from .stage1.request_builder import prepare_stage1_request
        from .stage1.result_handler import create_stage1_handler

        # Setup processor and handler
        stage_storage_dir = storage.stage(self.stage_storage.stage_name)
        log_dir = stage_storage_dir.output_dir / "logs" / "llmbatch"
        config = LLMBatchConfig(model=self.model, max_workers=self.max_workers, max_retries=self.max_retries)
        processor = LLMBatchProcessor(
            logger=logger,
            log_dir=log_dir,
            config=config,
            metrics_manager=stage_storage_dir.metrics_manager,
        )
        handler = create_stage1_handler(
            storage,
            self.stage_storage,
            logger,
            self.name,
            self.output_schema,
            self.model
        )

        # Process batch
        batch_stats = batch_process_with_preparation(
            stage_name="Label-Pages",
            pages=remaining_pages,
            request_builder=prepare_stage1_request,
            result_handler=handler,
            processor=processor,
            logger=logger,
            storage=storage,
            model=self.model,
            total_pages=total_pages,
        )

        progress = self.get_status(storage, logger)

        # Generate report if not exists
        if not progress["artifacts"]["report_exists"]:
            logger.info("=== Generating Report ===")

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

        # Record total stage runtime
        elapsed_time = time.time() - start_time
        runtime_metrics = stage_storage_dir.metrics_manager.get("stage_runtime")
        if not runtime_metrics:
            stage_storage_dir.metrics_manager.record(
                key="stage_runtime",
                time_seconds=elapsed_time
            )

        logger.info(
            "Label-pages complete",
            pages_processed=completed_pages,
            cost=f"${total_cost:.4f}",
            time=f"{elapsed_time:.1f}s"
        )

        return {
            "status": "success",
            "pages_processed": completed_pages,
            "cost_usd": total_cost,
            "time_seconds": elapsed_time
        }
