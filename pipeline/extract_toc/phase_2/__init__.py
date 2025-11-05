"""
Phase 2: OCR Text Extraction

OlmOCR extracts clean text from ToC pages.
Saves one markdown file per page for human readability and Phase 3 consumption.
"""

import time
from typing import Dict, Tuple
from pathlib import Path
from PIL import Image

from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.deepinfra import DeepInfraOCRBatchProcessor, OCRRequest, OCRResult

from ..schemas import PageRange
from ..storage import ExtractTocStageStorage


def extract_ocr_text(
    storage: BookStorage,
    toc_range: PageRange,
    logger: PipelineLogger
) -> Tuple[Dict[str, any], Dict[str, any]]:
    """
    Extract OCR text from ToC pages using OlmOCR (parallel batch processing).

    For each page:
    - Load source image
    - Run OlmOCR with markdown prompt (in parallel)
    - Save as page_NNNN.md file

    Args:
        storage: Book storage
        toc_range: Range of ToC pages
        logger: Pipeline logger

    Returns:
        Tuple of (results_data, metrics)
        - results_data: {"pages": [{"page_num": N, "md_file": "page_NNNN.md"}, ...]}
        - metrics: {"cost_usd": 0.0, "time_seconds": float, ...}
    """
    stage_storage = ExtractTocStageStorage(stage_name='extract-toc')
    stage_storage_obj = storage.stage('extract-toc')

    start_time = time.time()
    total_pages = toc_range.end_page - toc_range.start_page + 1

    logger.info(f"OCR processing {total_pages} ToC pages with OlmOCR (parallel)")

    # Build OCR requests for all pages
    requests = []
    source_storage = storage.stage("source")

    for page_num in range(toc_range.start_page, toc_range.end_page + 1):
        page_file = source_storage.output_dir / f"page_{page_num:04d}.png"

        if not page_file.exists():
            logger.error(f"  Page {page_num}: Source image not found: {page_file}")
            continue

        image = Image.open(page_file)
        prompt = "Extract all text from this Table of Contents page. Format the output as markdown, preserving the hierarchical structure and indentation."

        requests.append(OCRRequest(
            id=f"page_{page_num:04d}",
            image=image,
            prompt=prompt,
            metadata={"page_num": page_num}
        ))

    # Process batch with progress display
    page_results = []

    def handle_result(result: OCRResult):
        """Handle completed OCR result."""
        if result.success:
            page_num = result.request.metadata["page_num"]
            md_filename = f"page_{page_num:04d}.md"
            md_path = stage_storage_obj.output_dir / md_filename

            # Save markdown file
            with open(md_path, 'w', encoding='utf-8') as f:
                f.write(result.text)

            page_results.append({
                "page_num": page_num,
                "md_file": md_filename,
                "char_count": len(result.text)
            })

            # Record metrics
            stage_storage_obj.metrics_manager.record(
                key=f"phase2_page_{page_num:04d}",
                cost_usd=result.cost_usd,
                time_seconds=result.execution_time_seconds,
                custom_metrics={
                    "phase": "ocr_text",
                    "page": page_num,
                    "char_count": len(result.text),
                    "prompt_tokens": result.prompt_tokens,
                    "completion_tokens": result.completion_tokens,
                }
            )
        else:
            page_num = result.request.metadata["page_num"]
            logger.error(f"  Page {page_num}: OCR failed: {result.error_message}")

    # Create batch processor and run
    processor = DeepInfraOCRBatchProcessor(
        logger=logger,
        max_workers=4,  # DeepInfra can handle concurrent requests
        verbose=True,
        batch_name="OCR (OlmOCR)"
    )

    batch_stats = processor.process_batch(
        requests=requests,
        on_result=handle_result
    )

    elapsed_time = time.time() - start_time

    # Sort page_results by page_num
    page_results.sort(key=lambda p: p["page_num"])

    results_data = {
        "pages": page_results,
        "toc_range": toc_range.model_dump(),
    }

    metrics = {
        "cost_usd": batch_stats["total_cost_usd"],
        "time_seconds": elapsed_time,
        "pages_processed": len(page_results),
        "total_chars": sum(p["char_count"] for p in page_results),
        "prompt_tokens": batch_stats["total_tokens"],  # DeepInfra doesn't separate prompt/completion
        "completion_tokens": 0,  # Combined in total_tokens
    }

    return results_data, metrics
