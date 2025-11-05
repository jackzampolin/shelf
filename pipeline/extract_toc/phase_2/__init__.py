"""
Phase 1: Direct ToC Entry Extraction

Vision model extracts complete ToC entries (title + page number + hierarchy) in a single pass.
Loads OCR text directly from ocr-pages stage (no intermediate storage needed).
"""

import json
import time
from typing import Dict, Tuple
from pathlib import Path
from PIL import Image

from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.llm.batch_processor import LLMBatchProcessor, LLMBatchConfig
from infra.llm.models import LLMRequest, LLMResult
from infra.utils.pdf import downsample_for_vision
from infra.config import Config

from ..schemas import PageRange, ToCEntry
from ..storage import ExtractTocStageStorage
from .prompts import SYSTEM_PROMPT, build_user_prompt


def extract_toc_entries(
    storage: BookStorage,
    toc_range: PageRange,
    structure_notes_from_finder: Dict[int, str],
    logger: PipelineLogger,
    model: str = None
) -> Tuple[Dict[str, any], Dict[str, any]]:
    """
    Extract complete ToC entries directly from each page using vision model.

    For each page:
    - Load OCR text from ocr-pages stage
    - Load source image
    - Call vision model to extract complete ToC entries (title, page number, hierarchy level)
    - No intermediate storage or representation

    Args:
        storage: Book storage
        toc_range: Range of ToC pages
        structure_notes_from_finder: Map of page_num -> structure observations
        logger: Pipeline logger
        model: Vision model to use (default: Config.vision_model_primary)

    Returns:
        Tuple of (results_data, metrics)
        - results_data: {"pages": [{"page_num": N, "entries": [...], ...}, ...]}
        - metrics: {"cost_usd": float, "time_seconds": float, ...}
    """
    model = model or Config.vision_model_primary
    stage_storage = ExtractTocStageStorage(stage_name='extract-toc')
    stage_storage_obj = storage.stage('extract-toc')

    start_time = time.time()
    total_toc_pages = toc_range.end_page - toc_range.start_page + 1

    logger.info(f"Extracting ToC entries from {total_toc_pages} pages (parallel)")

    # Build LLM requests for all pages
    requests = []
    source_storage = storage.stage("source")

    # Load OCR text directly from ocr-pages stage
    from pipeline.ocr_pages.storage import OcrPagesStageStorage
    ocr_pages_storage = OcrPagesStageStorage(stage_name='ocr-pages')

    for page_num in range(toc_range.start_page, toc_range.end_page + 1):
        # Load OCR data from ocr-pages stage
        page_data = ocr_pages_storage.load_page(storage, page_num)

        if not page_data:
            logger.error(f"  Page {page_num}: OCR data not found in ocr-pages stage")
            continue

        ocr_text = page_data.get("text", "")

        page_file = source_storage.output_dir / f"page_{page_num:04d}.png"

        if not page_file.exists():
            logger.error(f"  Page {page_num}: Source image not found: {page_file}")
            continue

        image = Image.open(page_file)
        image = downsample_for_vision(image)

        page_structure_notes = structure_notes_from_finder.get(page_num, None)

        user_prompt = build_user_prompt(
            page_num=page_num,
            total_toc_pages=total_toc_pages,
            ocr_text=ocr_text,
            structure_notes=page_structure_notes
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ]

        requests.append(LLMRequest(
            id=f"page_{page_num:04d}",
            model=model,
            messages=messages,
            images=[image],
            temperature=0.0,
            response_format={"type": "json_object"},
            timeout=300,
            metadata={"page_num": page_num}
        ))

    # Process batch with LLMBatchProcessor
    page_results = []

    def handle_result(result: LLMResult):
        """Handle completed ToC entry extraction result."""
        if result.success:
            page_num = result.request.metadata["page_num"]

            try:
                response_data = json.loads(result.response)

                # Validate entries against ToCEntry schema
                entries_raw = response_data.get("entries", [])
                entries_validated = []

                for entry in entries_raw:
                    try:
                        validated_entry = ToCEntry(**entry)
                        entries_validated.append(validated_entry.model_dump())
                    except Exception as e:
                        logger.error(f"  Page {page_num}: Invalid entry {entry}: {e}")

                page_results.append({
                    "page_num": page_num,
                    "entries": entries_validated,
                    "page_metadata": response_data.get("page_metadata", {}),
                    "confidence": response_data.get("confidence", 0.0),
                    "notes": response_data.get("notes", "")
                })

                # Record metrics
                stage_storage_obj.metrics_manager.record(
                    key=f"phase1_page_{page_num:04d}",
                    cost_usd=result.cost_usd,
                    time_seconds=result.execution_time_seconds,
                    custom_metrics={
                        "phase": "extract_entries",
                        "page": page_num,
                        "entries_extracted": len(entries_validated),
                        "confidence": response_data.get("confidence", 0.0),
                        "prompt_tokens": result.prompt_tokens,
                        "completion_tokens": result.completion_tokens,
                        "reasoning_tokens": result.reasoning_tokens,
                    }
                )

            except Exception as e:
                logger.error(f"  Page {page_num}: Failed to parse ToC entry extraction: {e}")
        else:
            page_num = result.request.metadata["page_num"]
            logger.error(f"  Page {page_num}: Failed to extract ToC entries: {result.error_message}")

    # Create batch processor and run
    config = LLMBatchConfig(
        model=model,
        max_workers=4,  # Process 4 pages concurrently
        max_retries=3,
        verbose=True,
        batch_name="ToC entry extraction"
    )

    processor = LLMBatchProcessor(
        logger=logger,
        log_dir=stage_storage_obj.output_dir / "logs" / "phase1",
        config=config,
        metrics_manager=stage_storage_obj.metrics_manager
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

    total_entries = sum(len(p["entries"]) for p in page_results)

    metrics = {
        "cost_usd": batch_stats["total_cost_usd"],
        "time_seconds": elapsed_time,
        "prompt_tokens": 0,  # Not tracked separately by batch client
        "completion_tokens": batch_stats["total_tokens"],  # batch_stats.total_tokens = completion_tokens
        "reasoning_tokens": batch_stats["total_reasoning_tokens"],
        "pages_processed": len(page_results),
        "total_entries": total_entries,
    }

    return results_data, metrics
