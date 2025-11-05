import time
from typing import Dict, Any
from PIL import Image

from infra.pipeline.base_stage import BaseStage
from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.deepinfra import DeepInfraOCRBatchProcessor, OCRRequest, OCRResult

from .schemas import OcrPagesPageOutput
from .status import OcrPagesStatusTracker, OcrPagesStatus
from .storage import OcrPagesStageStorage


class OcrPagesStage(BaseStage):
    name = "ocr-pages"
    dependencies = ["source"]

    output_schema = OcrPagesPageOutput
    checkpoint_schema = None
    report_schema = None
    self_validating = True

    def __init__(self, max_workers: int = 30):
        super().__init__()
        self.max_workers = max_workers
        self.status_tracker = OcrPagesStatusTracker(stage_name=self.name)
        self.stage_storage = OcrPagesStageStorage(stage_name=self.name)

    def get_status(
        self,
        storage: BookStorage,
        logger: PipelineLogger
    ) -> Dict[str, Any]:
        return self.status_tracker.get_status(storage)

    def pretty_print_status(self, status: Dict[str, Any]) -> str:
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
        logger.info(f"OCR-Pages with OlmOCR (max_workers={self.max_workers})")

        source_stage = storage.stage("source")
        source_pages = source_stage.list_output_pages(extension="png")

        if len(source_pages) == 0:
            raise ValueError("No source pages found - cannot run ocr-pages stage")

        logger.info(f"Found {len(source_pages)} source pages")

    def run(
        self,
        storage: BookStorage,
        logger: PipelineLogger,
    ) -> Dict[str, Any]:
        start_time = time.time()

        progress = self.get_status(storage, logger)

        if progress["status"] == OcrPagesStatus.COMPLETED.value:
            logger.info("OCR-Pages already completed (skipping)")
            return {
                "status": "skipped",
                "reason": "already completed",
                "pages_processed": progress["completed_pages"]
            }

        total_pages = progress["total_pages"]
        remaining_pages = progress["remaining_pages"]

        logger.info(f"OCR-Pages Status: {progress['status']}")
        logger.info(f"Progress: {progress['completed_pages']}/{total_pages} pages complete")

        if len(remaining_pages) == 0:
            logger.info("No pages remaining to process")
            return {
                "status": "success",
                "pages_processed": 0
            }

        logger.info(f"Processing {len(remaining_pages)} remaining pages with OlmOCR")

        requests = []
        source_storage = storage.stage("source")

        for page_num in remaining_pages:
            page_file = source_storage.output_dir / f"page_{page_num:04d}.png"

            if not page_file.exists():
                logger.error(f"  Page {page_num}: Source image not found: {page_file}")
                continue

            image = Image.open(page_file)
            prompt = "Extract all text from this page. Format the output as clean markdown, preserving structure and formatting."

            requests.append(OCRRequest(
                id=f"page_{page_num:04d}",
                image=image,
                prompt=prompt,
                metadata={"page_num": page_num}
            ))

        stage_storage_obj = storage.stage(self.name)
        pages_processed = 0

        def handle_result(result: OCRResult):
            nonlocal pages_processed

            if result.success:
                page_num = result.request.metadata["page_num"]

                page_data = {
                    "page_num": page_num,
                    "text": result.text,
                    "char_count": len(result.text)
                }

                stage_storage_obj.save_page(
                    page_num,
                    page_data,
                    schema=self.output_schema
                )

                stage_storage_obj.metrics_manager.record(
                    key=f"page_{page_num:04d}",
                    cost_usd=result.cost_usd,
                    time_seconds=result.execution_time_seconds,
                    custom_metrics={
                        "page": page_num,
                        "char_count": len(result.text),
                        "prompt_tokens": result.prompt_tokens,
                        "completion_tokens": result.completion_tokens,
                    }
                )

                pages_processed += 1
            else:
                page_num = result.request.metadata["page_num"]
                logger.error(f"  Page {page_num}: OCR failed: {result.error_message}")

        processor = DeepInfraOCRBatchProcessor(
            logger=logger,
            max_workers=self.max_workers,
            verbose=True,
            batch_name="OCR Pages (OlmOCR)"
        )

        batch_stats = processor.process_batch(
            requests=requests,
            on_result=handle_result
        )

        elapsed_time = time.time() - start_time

        runtime_metrics = stage_storage_obj.metrics_manager.get("stage_runtime")
        if not runtime_metrics:
            stage_storage_obj.metrics_manager.record(
                key="stage_runtime",
                time_seconds=elapsed_time
            )

        logger.info(
            "OCR-Pages complete",
            pages_processed=pages_processed,
            cost=f"${batch_stats['total_cost_usd']:.4f}",
            time=f"{elapsed_time:.1f}s"
        )

        return {
            "status": "success",
            "pages_processed": pages_processed,
            "cost_usd": batch_stats["total_cost_usd"],
            "time_seconds": elapsed_time
        }
