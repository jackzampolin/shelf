"""
Phase 3: Element Identification

Vision model identifies structural elements using image + OCR text.
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

from ..schemas import PageRange
from ..storage import ExtractTocStageStorage
from .prompts import SYSTEM_PROMPT, build_user_prompt


def identify_elements(
    storage: BookStorage,
    toc_range: PageRange,
    structure_notes_from_finder: Dict[int, str],
    logger: PipelineLogger,
    model: str = None
) -> Tuple[Dict[str, any], Dict[str, any]]:
    """
    Identify structural elements using vision model + OCR text.

    For each page:
    - Load OCR text from Phase 2
    - Load source image
    - Call vision model with both image and OCR text
    - Save element identification results

    Args:
        storage: Book storage
        toc_range: Range of ToC pages
        structure_notes_from_finder: Map of page_num -> structure observations
        logger: Pipeline logger
        model: Vision model to use (default: Config.vision_model_primary)

    Returns:
        Tuple of (results_data, metrics)
        - results_data: {"pages": [{"page_num": N, "elements": [...], ...}, ...]}
        - metrics: {"cost_usd": float, "time_seconds": float, ...}
    """
    model = model or Config.vision_model_primary
    stage_storage = ExtractTocStageStorage(stage_name='extract-toc')
    stage_storage_obj = storage.stage('extract-toc')

    start_time = time.time()
    total_toc_pages = toc_range.end_page - toc_range.start_page + 1

    logger.info(f"Identifying elements from {total_toc_pages} ToC pages (parallel)")

    # Build LLM requests for all pages
    requests = []
    source_storage = storage.stage("source")

    for page_num in range(toc_range.start_page, toc_range.end_page + 1):
        md_path = stage_storage_obj.output_dir / f"page_{page_num:04d}.md"

        if not md_path.exists():
            logger.error(f"  Page {page_num}: OCR markdown not found: {md_path}")
            continue

        with open(md_path, 'r', encoding='utf-8') as f:
            ocr_text = f.read()

        page_file = source_storage.output_dir / f"page_{page_num:04d}.png"

        if not page_file.exists():
            logger.error(f"  Page {page_num}: Source image not found: {page_file}")
            continue

        image = Image.open(page_file)
        image = downsample_for_vision(image)

        page_structure_notes = structure_notes_from_finder.get(page_num, "No specific structure notes for this page.")

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
        """Handle completed element identification result."""
        if result.success:
            page_num = result.request.metadata["page_num"]

            try:
                response_data = json.loads(result.response)

                page_results.append({
                    "page_num": page_num,
                    "elements": response_data.get("elements", []),
                    "page_structure": response_data.get("page_structure", {}),
                    "confidence": response_data.get("confidence", 0.0),
                    "notes": response_data.get("notes", "")
                })

                # Metrics already recorded by batch processor's MetricsManager integration
                stage_storage_obj.metrics_manager.record(
                    key=f"phase3_page_{page_num:04d}",
                    cost_usd=result.cost_usd,
                    time_seconds=result.execution_time_seconds,
                    custom_metrics={
                        "phase": "identify_elements",
                        "page": page_num,
                        "elements_found": len(response_data.get("elements", [])),
                        "confidence": response_data.get("confidence", 0.0),
                        "prompt_tokens": result.prompt_tokens,
                        "completion_tokens": result.completion_tokens,
                        "reasoning_tokens": result.reasoning_tokens,
                    }
                )

            except Exception as e:
                logger.error(f"  Page {page_num}: Failed to parse element identification: {e}")
        else:
            page_num = result.request.metadata["page_num"]
            logger.error(f"  Page {page_num}: Failed to identify elements: {result.error_message}")

    # Create batch processor and run
    config = LLMBatchConfig(
        model=model,
        max_workers=4,  # Process 4 pages concurrently
        max_retries=3,
        verbose=True,
        batch_name="Element identification"
    )

    processor = LLMBatchProcessor(
        logger=logger,
        log_dir=stage_storage_obj.output_dir / "logs" / "phase3",
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

    total_elements = sum(len(p["elements"]) for p in page_results)

    metrics = {
        "cost_usd": batch_stats["total_cost_usd"],
        "time_seconds": elapsed_time,
        "prompt_tokens": 0,  # Not tracked separately by batch client
        "completion_tokens": batch_stats["total_tokens"],  # batch_stats.total_tokens = completion_tokens
        "reasoning_tokens": batch_stats["total_reasoning_tokens"],
        "pages_processed": len(page_results),
        "total_elements": total_elements,
    }

    return results_data, metrics
