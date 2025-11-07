from typing import Dict, Any, List
from PIL import Image

from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.deepinfra import DeepInfraOCRBatchProcessor, OCRRequest, OCRResult

from ..schemas import OcrPagesPageOutput


def process_batch(
    storage: BookStorage,
    logger: PipelineLogger,
    remaining_pages: List[int],
    max_workers: int
) -> Dict[str, Any]:

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

    stage_storage = storage.stage("ocr-pages")
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

            stage_storage.save_page(
                page_num,
                page_data,
                schema=OcrPagesPageOutput
            )

            stage_storage.metrics_manager.record(
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
        max_workers=max_workers,
        verbose=True,
        batch_name="OCR Pages (OlmOCR)"
    )

    batch_stats = processor.process_batch(
        requests=requests,
        on_result=handle_result
    )

    logger.info(
        "OCR-Pages complete",
        pages_processed=pages_processed,
        cost=f"${batch_stats['total_cost_usd']:.4f}"
    )

    return {
        "status": "success",
        "pages_processed": pages_processed,
        "cost_usd": batch_stats["total_cost_usd"]
    }
