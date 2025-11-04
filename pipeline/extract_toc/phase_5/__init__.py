"""
Phase 5: ToC Assembly

LLM interprets OCR'd text boxes and their positions to build ToC entries.
"""

import json
import time
from typing import List, Dict, Tuple
from pathlib import Path

from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.llm.client import LLMClient
from infra.config import Config

from ..schemas import PageRange, TocPageAssembly, ToCEntry
from ..storage import ExtractTocStageStorage
from .prompts import SYSTEM_PROMPT, build_user_prompt
from .progress import TocAssemblyProgress


def assemble_toc(
    storage: BookStorage,
    toc_range: PageRange,
    logger: PipelineLogger,
    model: str = None
) -> Tuple[Dict[str, any], Dict[str, any]]:
    """
    Assemble ToC entries from OCR'd text boxes.

    Processes pages sequentially, using prior page context for continuity.

    Args:
        storage: Book storage
        toc_range: Range of ToC pages
        logger: Pipeline logger
        model: Text model to use (default: Config.text_model_expensive)

    Returns:
        Tuple of (results_data, metrics)
        - results_data: {"pages": [TocPageAssembly, ...]}
        - metrics: {"cost_usd": float, "time_seconds": float, ...}
    """
    model = model or Config.text_model_expensive
    llm_client = LLMClient()
    stage_storage = ExtractTocStageStorage(stage_name='extract-toc')

    # Load Phase 4 OCR results
    bboxes_ocr = stage_storage.load_bboxes_ocr(storage)
    pages_data = {p["page_num"]: p for p in bboxes_ocr["pages"]}

    start_time = time.time()
    total_cost = 0.0
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_reasoning_tokens = 0
    total_entries = 0

    page_results = []
    prior_page_notes = None

    total_toc_pages = len(pages_data)

    logger.info(f"Assembling ToC from {total_toc_pages} pages")

    with TocAssemblyProgress(total_pages=total_toc_pages) as progress:
        for page_num in range(toc_range.start_page, toc_range.end_page + 1):
            page_data = pages_data.get(page_num)
            if not page_data:
                logger.warning(f"  Page {page_num}: No OCR data from Phase 4, skipping")
                continue

            # Reconstruct BboxPageOCR
            from ..schemas import BboxPageOCR
            ocr_page = BboxPageOCR(**page_data)

            # Start progress for this page
            progress.start_page(page_num, f"Assembling page {page_num} ({len(ocr_page.ocr_results)} boxes)...")

            # Format OCR boxes for prompt
            ocr_boxes = []
            for ocr_result in ocr_page.ocr_results:
                ocr_boxes.append({
                    "bbox": {
                        "x": ocr_result.bbox.x,
                        "y": ocr_result.bbox.y,
                        "width": ocr_result.bbox.width,
                        "height": ocr_result.bbox.height,
                    },
                    "text": ocr_result.text,
                    "confidence": ocr_result.confidence,
                })

            # Build prompt
            user_prompt = build_user_prompt(
                page_num=page_num,
                total_toc_pages=total_toc_pages,
                ocr_boxes=ocr_boxes,
                prior_page_context=prior_page_notes
            )

            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ]

            # Call LLM
            page_start = time.time()
            response_text, usage, cost = llm_client.call(
                model=model,
                messages=messages,
                temperature=0.0,
                response_format={"type": "json_object"}
            )
            page_time = time.time() - page_start

            # Parse response
            try:
                response_data = json.loads(response_text)

                entries_raw = response_data.get("entries", [])
                assembly_confidence = response_data.get("assembly_confidence", 0.0)
                notes = response_data.get("notes", "")
                prior_context_used = response_data.get("prior_context_used", False)

                # Convert to ToCEntry objects
                entries = [ToCEntry(**entry) for entry in entries_raw]

                page_assembly = TocPageAssembly(
                    page_num=page_num,
                    entries=entries,
                    assembly_confidence=assembly_confidence,
                    notes=notes,
                    prior_context_used=prior_context_used
                )

                page_results.append(page_assembly.model_dump())

                # Update prior page context for next iteration
                prior_page_notes = notes

                # Accumulate metrics
                total_cost += cost
                total_prompt_tokens += usage.get("prompt_tokens", 0)
                total_completion_tokens += usage.get("completion_tokens", 0)
                reasoning_details = usage.get("completion_tokens_details", {})
                total_reasoning_tokens += reasoning_details.get("reasoning_tokens", 0)
                total_entries += len(entries)

                # Record page-level metrics
                stage_storage_obj = storage.stage('extract-toc')
                stage_storage_obj.metrics_manager.record(
                    key=f"phase5_page_{page_num:04d}",
                    cost_usd=cost,
                    time_seconds=page_time,
                    custom_metrics={
                        "phase": "toc_assembly",
                        "page": page_num,
                        "entries_found": len(entries),
                        "assembly_confidence": assembly_confidence,
                        "prior_context_used": prior_context_used,
                        "prompt_tokens": usage.get("prompt_tokens", 0),
                        "completion_tokens": usage.get("completion_tokens", 0),
                        "reasoning_tokens": reasoning_details.get("reasoning_tokens", 0),
                    }
                )

                # Update progress with completion
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)
                reasoning_tokens = reasoning_details.get("reasoning_tokens", 0)

                result_summary = f"{len(entries)} entries | conf: {assembly_confidence:.2f} | {page_time:.1f}s | {prompt_tokens}in→{completion_tokens}out+{reasoning_tokens}r | ${cost:.4f}"
                progress.complete_page(page_num, result_summary)

            except Exception as e:
                logger.error(f"    ✗ Failed to assemble page {page_num}: {e}")
                raise

    elapsed_time = time.time() - start_time

    results_data = {
        "pages": page_results,
        "toc_range": toc_range.model_dump(),
    }

    metrics = {
        "cost_usd": total_cost,
        "time_seconds": elapsed_time,
        "prompt_tokens": total_prompt_tokens,
        "completion_tokens": total_completion_tokens,
        "reasoning_tokens": total_reasoning_tokens,
        "pages_processed": len(page_results),
        "total_entries": total_entries,
    }

    return results_data, metrics
