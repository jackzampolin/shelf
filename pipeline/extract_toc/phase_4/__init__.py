"""
Phase 4: Bounding Box OCR

Tesseract extracts text from each verified bounding box.
"""

import time
import pytesseract
from typing import List, Dict, Tuple
from pathlib import Path
from PIL import Image
import statistics

from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger

from ..schemas import PageRange, BboxPageOCR, BboxOCRText
from ..storage import ExtractTocStageStorage
from .progress import BboxOCRProgress

from pipeline.ocr.schemas.bounding_box import BoundingBox


def ocr_bboxes(
    storage: BookStorage,
    toc_range: PageRange,
    logger: PipelineLogger
) -> Tuple[Dict[str, any], Dict[str, any]]:
    """
    OCR each verified bounding box using Tesseract.

    For each page:
    - Load verified bboxes from Phase 3
    - Load source image
    - Crop and OCR each bbox
    - Store text + confidence

    Args:
        storage: Book storage
        toc_range: Range of ToC pages
        logger: Pipeline logger

    Returns:
        Tuple of (results_data, metrics)
        - results_data: {"pages": [BboxPageOCR, ...]}
        - metrics: {"cost_usd": 0.0, "time_seconds": float, ...}
    """
    stage_storage = ExtractTocStageStorage(stage_name='extract-toc')

    # Load Phase 3 verification results
    bboxes_verified = stage_storage.load_bboxes_verified(storage)
    pages_data = {p["page_num"]: p for p in bboxes_verified["pages"]}

    start_time = time.time()
    total_bboxes = 0
    total_confidence_sum = 0.0

    page_results = []
    total_toc_pages = len(pages_data)

    logger.info(f"OCR processing {total_toc_pages} ToC pages")

    # Get Tesseract version once
    tesseract_version = str(pytesseract.get_tesseract_version())

    with BboxOCRProgress(total_pages=total_toc_pages) as progress:
        for page_num in range(toc_range.start_page, toc_range.end_page + 1):
            page_data = pages_data.get(page_num)
            if not page_data:
                logger.warning(f"  Page {page_num}: No bbox data from Phase 3, skipping")
                continue

            # Reconstruct BboxPageVerified
            from ..schemas import BboxPageVerified
            verified = BboxPageVerified(**page_data)

            # Start progress for this page
            progress.start_page(page_num, f"OCR processing page {page_num} ({len(verified.bboxes)} boxes)...")

            # Load source image
            source_storage = storage.stage("source")
            page_file = source_storage.output_dir / f"page_{page_num:04d}.png"

            if not page_file.exists():
                logger.error(f"    ✗ Source image not found: {page_file}")
                continue

            page_start = time.time()
            image = Image.open(page_file)

            # OCR each bbox
            ocr_results = []
            confidences = []

            for bbox in verified.bboxes:
                ocr_text = _ocr_bbox_region(image, bbox)
                ocr_results.append(ocr_text)
                confidences.append(ocr_text.confidence)

            # Calculate average confidence for page
            avg_confidence = statistics.mean(confidences) if confidences else 0.0

            page_ocr = BboxPageOCR(
                page_num=page_num,
                ocr_results=ocr_results,
                avg_confidence=avg_confidence,
                tesseract_version=tesseract_version
            )

            page_results.append(page_ocr.model_dump())

            # Accumulate metrics
            total_bboxes += len(ocr_results)
            total_confidence_sum += avg_confidence

            page_time = time.time() - page_start

            # Record page-level metrics
            stage_storage_obj = storage.stage('extract-toc')
            stage_storage_obj.metrics_manager.record(
                key=f"phase4_page_{page_num:04d}",
                time_seconds=page_time,
                custom_metrics={
                    "phase": "bbox_ocr",
                    "page": page_num,
                    "bboxes_ocr": len(ocr_results),
                    "avg_confidence": avg_confidence,
                }
            )

            # Update progress with completion
            result_summary = f"{len(ocr_results)} boxes | avg conf: {avg_confidence:.1f}% | {page_time:.1f}s"
            progress.complete_page(page_num, result_summary)

    elapsed_time = time.time() - start_time

    results_data = {
        "pages": page_results,
        "toc_range": toc_range.model_dump(),
    }

    metrics = {
        "cost_usd": 0.0,  # Tesseract is free
        "time_seconds": elapsed_time,
        "pages_processed": len(page_results),
        "total_bboxes": total_bboxes,
        "avg_confidence": total_confidence_sum / len(page_results) if page_results else 0.0,
    }

    return results_data, metrics


def _ocr_bbox_region(image: Image.Image, bbox: BoundingBox) -> BboxOCRText:
    """
    OCR a single bounding box region.

    Uses PSM 7 (single text line) for ToC entries.
    """
    # Crop bbox region
    left = bbox.x
    top = bbox.y
    right = bbox.x + bbox.width
    bottom = bbox.y + bbox.height

    cropped = image.crop((left, top, right, bottom))

    # OCR with PSM 7 (single text line) - most ToC entries are single lines
    config = "--psm 7"

    # Extract text
    text = pytesseract.image_to_string(cropped, lang="eng", config=config)
    text = text.strip()

    # Get confidence
    data = pytesseract.image_to_data(
        cropped,
        lang="eng",
        config=config,
        output_type=pytesseract.Output.DICT
    )

    # Calculate average confidence from word-level confidences
    confidences = [
        int(conf) for conf in data.get("conf", [])
        if conf != -1  # -1 means no confidence (empty detection)
    ]
    avg_confidence = statistics.mean(confidences) if confidences else 0.0

    return BboxOCRText(
        bbox=bbox,
        text=text,
        confidence=avg_confidence
    )
