import threading
from typing import Dict, Any, List
from concurrent.futures import ThreadPoolExecutor, as_completed

from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.pipeline.rich_progress import RichProgressBar

from ..schemas import TesseractPageOutput
from .worker import process_page_with_tesseract


def process_batch(
    storage: BookStorage,
    logger: PipelineLogger,
    remaining_pages: List[int],
    psm_mode: int,
    max_workers: int
) -> Dict[str, Any]:

    source_storage = storage.stage("source")
    stage_storage = storage.stage("tesseract")

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

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
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
                psm_mode
            )
            future_to_page[future] = page_num

        for future in as_completed(future_to_page):
            page_num = future_to_page[future]

            try:
                page_data = future.result()

                stage_storage.save_page(
                    page_num,
                    page_data,
                    schema=TesseractPageOutput
                )

                stage_storage.metrics_manager.record(
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

    avg_confidence = total_confidence / pages_processed if pages_processed > 0 else 0.0

    completion_msg = (
        f"✓ Tesseract complete: {pages_processed} pages, "
        f"{total_paragraphs} paragraphs, "
        f"avg conf={avg_confidence:.1%}"
    )
    progress.finish(completion_msg)

    logger.info(
        "Tesseract complete",
        pages_processed=pages_processed,
        paragraphs=total_paragraphs,
        avg_confidence=f"{avg_confidence:.1%}"
    )

    return {
        "status": "success",
        "pages_processed": pages_processed
    }
