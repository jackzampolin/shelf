import time
import threading
import multiprocessing
from typing import Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

from infra.pipeline.base_stage import BaseStage
from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.pipeline.rich_progress import RichProgressBar
from infra.pipeline.status import BatchBasedStatusTracker

from .schemas import TesseractPageOutput
from .storage import TesseractStageStorage
from .tools.worker import process_page_with_tesseract


class TesseractStage(BaseStage):
    name = "tesseract"
    dependencies = ["source"]

    output_schema = TesseractPageOutput
    checkpoint_schema = None
    report_schema = None
    self_validating = True

    def __init__(self, psm_mode: int = 3, max_workers: int = None):
        super().__init__()
        self.psm_mode = psm_mode
        self.max_workers = max_workers or multiprocessing.cpu_count()
        self.status_tracker = BatchBasedStatusTracker(
            stage_name=self.name,
            source_stage="source",
            item_pattern="page_{:04d}.json"
        )
        self.stage_storage = TesseractStageStorage(stage_name=self.name)


    def before(
        self,
        storage: BookStorage,
        logger: PipelineLogger
    ):
        logger.info(f"Tesseract OCR (PSM {self.psm_mode}, {self.max_workers} workers)")

        source_stage = storage.stage("source")
        source_pages = source_stage.list_output_pages(extension="png")

        if len(source_pages) == 0:
            raise ValueError("No source pages found - cannot run tesseract stage")

        logger.info(f"Found {len(source_pages)} source pages")

    def run(
        self,
        storage: BookStorage,
        logger: PipelineLogger,
    ) -> Dict[str, Any]:
        start_time = time.time()

        progress = self.get_status(storage, logger)

        if progress["status"] == "completed":
            logger.info("Tesseract already completed (skipping)")
            return {
                "status": "skipped",
                "reason": "already completed",
                "pages_processed": progress["progress"]["completed_items"]
            }

        total_pages = progress["progress"]["total_items"]
        remaining_pages = progress["progress"]["remaining_items"]

        logger.info(f"Tesseract Status: {progress['status']}")
        logger.info(f"Progress: {progress['progress']['completed_items']}/{total_pages} pages complete")

        if len(remaining_pages) == 0:
            logger.info("No pages remaining to process")
            return {
                "status": "success",
                "pages_processed": 0
            }

        logger.info(f"Processing {len(remaining_pages)} pages with Tesseract PSM {self.psm_mode}")

        source_storage = storage.stage("source")
        stage_storage_obj = storage.stage(self.name)
        pages_processed = 0
        total_confidence = 0.0
        total_paragraphs = 0

        progress = RichProgressBar(
            total=len(remaining_pages),
            prefix="   ",
            width=40,
            unit="pages",
        )
        progress.update(0, suffix="starting...")

        completed = 0
        lock = threading.Lock()

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_page = {}

            for page_num in remaining_pages:
                page_file = source_storage.output_dir / f"page_{page_num:04d}.png"

                if not page_file.exists():
                    logger.error(f"  Page {page_num}: Source image not found: {page_file}")
                    continue

                future = executor.submit(
                    process_page_with_tesseract,
                    page_file,
                    page_num,
                    self.psm_mode
                )
                future_to_page[future] = page_num

            for future in as_completed(future_to_page):
                page_num = future_to_page[future]

                try:
                    page_data = future.result()

                    stage_storage_obj.save_page(
                        page_num,
                        page_data,
                        schema=self.output_schema
                    )

                    stage_storage_obj.metrics_manager.record(
                        key=f"page_{page_num:04d}",
                        time_seconds=page_data["processing_time_seconds"],
                        custom_metrics={
                            "page": page_num,
                            "paragraphs_count": len(page_data["paragraphs"]),
                            "avg_confidence": page_data["avg_confidence"],
                        }
                    )

                    with lock:
                        completed += 1
                        pages_processed += 1
                        total_confidence += page_data["avg_confidence"]
                        total_paragraphs += len(page_data["paragraphs"])
                        progress.update(
                            completed,
                            suffix=f"{completed}/{len(remaining_pages)} | "
                                   f"conf={page_data['avg_confidence']:.2f}"
                        )

                except Exception as e:
                    logger.error(f"  Page {page_num}: Processing failed: {e}")
                    with lock:
                        completed += 1
                        progress.update(completed, suffix=f"{completed}/{len(remaining_pages)} | ERROR")

        elapsed_time = time.time() - start_time
        avg_confidence = total_confidence / pages_processed if pages_processed > 0 else 0.0

        completion_msg = (
            f"✓ Tesseract complete: {pages_processed} pages, "
            f"{total_paragraphs} paragraphs, "
            f"avg conf={avg_confidence:.1%}, "
            f"time={elapsed_time:.1f}s"
        )
        progress.finish(completion_msg)

        stage_storage_obj.metrics_manager.record(
            key="stage_runtime",
            time_seconds=elapsed_time,
            accumulate=True
        )

        logger.info(
            "Tesseract complete",
            pages_processed=pages_processed,
            paragraphs=total_paragraphs,
            avg_confidence=f"{avg_confidence:.1%}",
            time=f"{elapsed_time:.1f}s"
        )

        return {
            "status": "success",
            "pages_processed": pages_processed,
            "time_seconds": elapsed_time
        }
