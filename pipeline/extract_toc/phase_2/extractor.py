"""
Phase 2: Bounding Box Extraction

Vision model places bounding boxes around ToC structural elements.
Processes pages sequentially, providing prior page context for continuation.
"""

import json
import time
from typing import List, Dict, Optional, Tuple
from pathlib import Path
from PIL import Image

from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.llm.client import LLMClient
from infra.utils.pdf import downsample_for_vision
from infra.config import Config

from ..schemas import PageRange, BboxPageExtraction
from ..storage import ExtractTocStageStorage
from .prompts import SYSTEM_PROMPT, build_user_prompt
from .progress import BboxExtractionProgress

from pipeline.ocr.schemas.bounding_box import BoundingBox


def extract_bboxes(
    storage: BookStorage,
    toc_range: PageRange,
    structure_notes_from_finder: Dict[int, str],
    logger: PipelineLogger,
    model: str = None
) -> Tuple[Dict[str, any], Dict[str, any]]:
    """
    Extract bounding boxes from ToC pages using vision model.

    Processes pages sequentially, providing each page with:
    - Structure notes from Phase 1 finder
    - Optional context from previous page

    Args:
        storage: Book storage
        toc_range: Range of ToC pages
        structure_notes_from_finder: Map of page_num -> structure observations
        logger: Pipeline logger
        model: Vision model to use (default: Config.vision_model_primary)

    Returns:
        Tuple of (results_data, metrics)
        - results_data: {"pages": [BboxPageExtraction, ...]}
        - metrics: {"cost_usd": float, "time_seconds": float, ...}
    """
    model = model or Config.vision_model_primary
    llm_client = LLMClient()
    stage_storage = ExtractTocStageStorage(stage_name='extract-toc')

    start_time = time.time()
    total_cost = 0.0
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_reasoning_tokens = 0

    page_results = []
    prior_page_notes = None

    # Load all ToC images
    logger.info("Loading ToC page images...")
    toc_images = _load_toc_images(storage, toc_range)
    total_toc_pages = len(toc_images)

    logger.info(f"Extracting bboxes from {total_toc_pages} ToC pages (sequential)")

    with BboxExtractionProgress(total_pages=total_toc_pages) as progress:
        for idx, page_num in enumerate(range(toc_range.start_page, toc_range.end_page + 1)):
            image = toc_images[idx]
            page_structure_notes = structure_notes_from_finder.get(page_num, "No specific structure notes for this page.")

            # Start progress display for this page
            progress.start_page(page_num, f"Calling vision model for page {page_num}...")

            # Build prompt with structure notes + optional prior context + image dimensions
            user_prompt = build_user_prompt(
                page_num=page_num,
                total_toc_pages=total_toc_pages,
                structure_notes=page_structure_notes,
                prior_page_notes=prior_page_notes,
                image_width=image.width,
                image_height=image.height
            )

            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ]

            # Call vision model
            page_start = time.time()
            response_text, usage, cost = llm_client.call(
                model=model,
                messages=messages,
                images=[image],
                temperature=0.0,
                response_format={"type": "json_object"},
                timeout=300  # 5 minutes for large ToC pages
            )
            page_time = time.time() - page_start

            # Parse response
            try:
                response_data = json.loads(response_text)
                bboxes_raw = response_data.get("bboxes", [])
                confidence = response_data.get("confidence", 0.0)
                notes = response_data.get("notes", "")

                # Convert to BoundingBox objects
                bboxes = [
                    BoundingBox(
                        x=bbox["x"],
                        y=bbox["y"],
                        width=bbox["width"],
                        height=bbox["height"]
                    )
                    for bbox in bboxes_raw
                ]

                page_extraction = BboxPageExtraction(
                    page_num=page_num,
                    bboxes=bboxes,
                    extraction_confidence=confidence,
                    notes=notes
                )

                page_results.append(page_extraction.model_dump())

                # Update prior page context for next iteration
                prior_page_notes = notes

                # Accumulate metrics
                total_cost += cost
                total_prompt_tokens += usage.get("prompt_tokens", 0)
                total_completion_tokens += usage.get("completion_tokens", 0)
                reasoning_details = usage.get("completion_tokens_details", {})
                total_reasoning_tokens += reasoning_details.get("reasoning_tokens", 0)

                # Record page-level metrics
                stage_storage_obj = storage.stage('extract-toc')
                stage_storage_obj.metrics_manager.record(
                    key=f"phase2_page_{page_num:04d}",
                    cost_usd=cost,
                    time_seconds=page_time,
                    custom_metrics={
                        "phase": "bbox_extraction",
                        "page": page_num,
                        "bboxes_found": len(bboxes),
                        "confidence": confidence,
                        "prompt_tokens": usage.get("prompt_tokens", 0),
                        "completion_tokens": usage.get("completion_tokens", 0),
                        "reasoning_tokens": reasoning_details.get("reasoning_tokens", 0),
                    }
                )

                # Update progress with completion
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)
                reasoning_tokens = reasoning_details.get("reasoning_tokens", 0)

                result_summary = f"{len(bboxes)} boxes | {page_time:.1f}s | {prompt_tokens}in→{completion_tokens}out+{reasoning_tokens}r | ${cost:.4f}"
                progress.complete_page(page_num, result_summary)

            except Exception as e:
                logger.error(f"    ✗ Failed to parse bbox extraction for page {page_num}: {e}")
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
    }

    return results_data, metrics


def _load_toc_images(storage: BookStorage, toc_range: PageRange) -> List[Image.Image]:
    """Load and downsample ToC page images."""
    source_storage = storage.stage("source")
    toc_images = []

    for page_num in range(toc_range.start_page, toc_range.end_page + 1):
        page_file = source_storage.output_dir / f"page_{page_num:04d}.png"
        if page_file.exists():
            image = Image.open(page_file)
            image = downsample_for_vision(image)
            toc_images.append(image)
        else:
            raise FileNotFoundError(f"ToC page not found: {page_file}")

    return toc_images
