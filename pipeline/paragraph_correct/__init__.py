from typing import Dict, Any

from infra.pipeline.base_stage import BaseStage
from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger

from .vision.schemas import ParagraphCorrectPageOutput, ParagraphCorrectPageMetrics, ParagraphCorrectPageReport
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

    def get_status(
        self,
        storage: BookStorage,
        logger: PipelineLogger
    ) -> Dict[str, Any]:
        return self.status_tracker.get_status(storage)

    def pretty_print_status(self, status: Dict[str, Any]) -> str:
        """Return formatted paragraph-correct status with corrections and confidence."""
        lines = [super().pretty_print_status(status)]

        # Paragraph-correct specific: corrections and confidence
        metrics = status.get('metrics', {})
        total_corrections = metrics.get('total_corrections', 0)
        avg_confidence = metrics.get('avg_confidence', 0.0)

        if total_corrections > 0:
            lines.append(f"   Corrections: {total_corrections} total")
        if avg_confidence > 0:
            lines.append(f"   Avg Confidence: {avg_confidence:.2%}")

        return '\n'.join(lines)

    def before(
        self,
        storage: BookStorage,
        logger: PipelineLogger
    ):
        logger.info(f"Paragraph-Correct with {self.model}")
        logger.info(f"Max workers: {self.max_workers}")

        from pipeline.ocr import OCRStage
        ocr_stage = OCRStage()

        ocr_progress = ocr_stage.get_status(storage, logger)

        if ocr_progress['status'] != 'completed':
            raise RuntimeError(
                f"OCR stage status is '{ocr_progress['status']}', not 'completed'. "
                f"Run OCR stage to completion first."
            )

        logger.info(f"OCR completed: {ocr_progress['total_pages']} pages ready for correction")

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

        # Phase 1: Vision-based correction (parallel processing)
        if status in [ParagraphCorrectStatus.NOT_STARTED.value, ParagraphCorrectStatus.CORRECTING.value]:
            remaining_pages = progress["remaining_pages"]

            if len(remaining_pages) > 0:
                logger.info("=== Phase 1: Vision-Based Correction ===")

                from infra.llm.batch_processor import LLMBatchProcessor, LLMBatchConfig, batch_process_with_preparation
                from .vision.request_builder import prepare_correction_request
                from .vision.result_handler import create_correction_handler

                # Build requests and collect page data map
                logger.info(f"Loading {len(remaining_pages)} pages...")
                page_data_map = {}

                def build_request(page_num: int):
                    try:
                        request, ocr_page = prepare_correction_request(
                            page_num=page_num,
                            storage=storage,
                            model=self.model,
                            total_pages=total_pages,
                        )
                        page_data_map[page_num] = ocr_page
                        return request
                    except Exception as e:
                        logger.error(f"Failed to prepare page {page_num}", page=page_num, error=str(e))
                        return None

                # Configure processor
                config = LLMBatchConfig(
                    model=self.model,
                    max_workers=self.max_workers,
                    max_retries=self.max_retries,
                )

                log_dir = storage.stage(self.name).output_dir / "logs"
                processor = LLMBatchProcessor(
                    checkpoint=None,
                    logger=logger,
                    log_dir=log_dir,
                    config=config,
                )

                # Create handler with page data map
                handler = create_correction_handler(
                    storage=storage,
                    stage_storage=self.stage_storage,
                    logger=logger,
                    output_schema=self.output_schema,
                    stage_name=self.name,
                    page_data_map=page_data_map,
                )

                # Process batch
                batch_process_with_preparation(
                    stage_name="Paragraph Correction",
                    pages=remaining_pages,
                    request_builder=build_request,
                    result_handler=handler,
                    processor=processor,
                    logger=logger,
                )

                progress = self.get_status(storage, logger)

        # Phase 2: Generate quality report (CSV with similarity metrics)
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
