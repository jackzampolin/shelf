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
from infra.deepinfra import OlmOCRProvider

from ..schemas import PageRange
from ..storage import ExtractTocStageStorage


def extract_ocr_text(
    storage: BookStorage,
    toc_range: PageRange,
    logger: PipelineLogger
) -> Tuple[Dict[str, any], Dict[str, any]]:
    """
    Extract OCR text from ToC pages using OlmOCR.

    For each page:
    - Load source image
    - Run OlmOCR with markdown prompt
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
    ocr_provider = OlmOCRProvider()

    start_time = time.time()
    total_pages = toc_range.end_page - toc_range.start_page + 1

    logger.info(f"OCR processing {total_pages} ToC pages with OlmOCR")

    page_results = []

    for page_num in range(toc_range.start_page, toc_range.end_page + 1):
        page_start = time.time()

        source_storage = storage.stage("source")
        page_file = source_storage.output_dir / f"page_{page_num:04d}.png"

        if not page_file.exists():
            logger.error(f"  Page {page_num}: Source image not found: {page_file}")
            continue

        logger.info(f"  Page {page_num}: Running OlmOCR...")

        image = Image.open(page_file)

        prompt = "Extract all text from this Table of Contents page. Format the output as markdown, preserving the hierarchical structure and indentation."

        ocr_text = ocr_provider.extract_text(image, prompt=prompt)

        md_filename = f"page_{page_num:04d}.md"
        stage_storage_obj = storage.stage('extract-toc')
        md_path = stage_storage_obj.output_dir / md_filename

        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(ocr_text)

        page_time = time.time() - page_start

        page_results.append({
            "page_num": page_num,
            "md_file": md_filename,
            "char_count": len(ocr_text)
        })

        stage_storage_obj.metrics_manager.record(
            key=f"phase2_page_{page_num:04d}",
            time_seconds=page_time,
            custom_metrics={
                "phase": "ocr_text",
                "page": page_num,
                "char_count": len(ocr_text),
            }
        )

        logger.info(f"  Page {page_num}: Saved {md_filename} ({len(ocr_text)} chars, {page_time:.1f}s)")

    elapsed_time = time.time() - start_time

    results_data = {
        "pages": page_results,
        "toc_range": toc_range.model_dump(),
    }

    metrics = {
        "cost_usd": 0.0,
        "time_seconds": elapsed_time,
        "pages_processed": len(page_results),
        "total_chars": sum(p["char_count"] for p in page_results),
    }

    return results_data, metrics
