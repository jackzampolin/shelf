"""
Phase 3: Bounding Box Verification

Self-verification without confirmation bias.
Vision model reviews its bbox placement through objective counting tasks.
"""

import json
import time
from typing import List, Dict, Tuple
from pathlib import Path
from PIL import Image, ImageDraw

from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.llm.client import LLMClient
from infra.utils.pdf import downsample_for_vision
from infra.config import Config

from ..schemas import PageRange, BboxPageVerified, BboxPageExtraction
from ..storage import ExtractTocStageStorage
from .prompts import SYSTEM_PROMPT, build_user_prompt
from .progress import BboxVerificationProgress

from pipeline.ocr.schemas.bounding_box import BoundingBox


def verify_bboxes(
    storage: BookStorage,
    toc_range: PageRange,
    logger: PipelineLogger,
    model: str = None
) -> Tuple[Dict[str, any], Dict[str, any]]:
    """
    Verify bounding boxes through objective counting and comparison.

    For each page:
    - Load image with bboxes visualized
    - Model counts elements vs boxes
    - Model reports differences and corrections
    - Apply corrections to produce verified bboxes

    Args:
        storage: Book storage
        toc_range: Range of ToC pages
        logger: Pipeline logger
        model: Vision model to use (default: Config.vision_model_primary)

    Returns:
        Tuple of (results_data, metrics)
        - results_data: {"pages": [BboxPageVerified, ...]}
        - metrics: {"cost_usd": float, "time_seconds": float, ...}
    """
    model = model or Config.vision_model_primary
    llm_client = LLMClient()
    stage_storage = ExtractTocStageStorage(stage_name='extract-toc')

    # Load Phase 2 extraction results
    bboxes_extracted = stage_storage.load_bboxes_extracted(storage)
    pages_data = {p["page_num"]: p for p in bboxes_extracted["pages"]}

    start_time = time.time()
    total_cost = 0.0
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_reasoning_tokens = 0
    total_corrections = 0

    page_results = []
    total_toc_pages = len(pages_data)

    logger.info(f"Verifying bboxes for {total_toc_pages} ToC pages")

    with BboxVerificationProgress(total_pages=total_toc_pages) as progress:
        for page_num in range(toc_range.start_page, toc_range.end_page + 1):
            page_data = pages_data.get(page_num)
            if not page_data:
                logger.warning(f"  Page {page_num}: No bbox data from Phase 2, skipping")
                continue

            # Reconstruct BboxPageExtraction
            extraction = BboxPageExtraction(**page_data)

            # Start progress for this page
            progress.start_page(page_num, f"Verifying page {page_num} ({len(extraction.bboxes)} boxes)...")

            # Load source image and draw bboxes on it
            source_storage = storage.stage("source")
            page_file = source_storage.output_dir / f"page_{page_num:04d}.png"

            if not page_file.exists():
                logger.error(f"    ✗ Source image not found: {page_file}")
                continue

            image = Image.open(page_file)
            image_with_boxes = _draw_bboxes_on_image(image, extraction.bboxes)
            image_with_boxes = downsample_for_vision(image_with_boxes)

            # Build prompt
            user_prompt = build_user_prompt(
                page_num=page_num,
                total_toc_pages=total_toc_pages,
                bboxes_count=len(extraction.bboxes),
                extraction_notes=extraction.notes
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
                images=[image_with_boxes],
                temperature=0.0,
                response_format={"type": "json_object"}
            )
            page_time = time.time() - page_start

            # Parse response and apply corrections
            try:
                response_data = json.loads(response_text)

                verification_passed = response_data.get("verification_passed", False)
                corrections_made = len(response_data.get("corrections", []))
                verification_notes = response_data.get("notes", "")

                # Apply corrections to bbox list
                verified_bboxes = _apply_corrections(
                    original_bboxes=extraction.bboxes,
                    corrections=response_data.get("corrections", [])
                )

                # Sort by Y position (top to bottom)
                verified_bboxes.sort(key=lambda bbox: bbox.y)

                page_verified = BboxPageVerified(
                    page_num=page_num,
                    bboxes=verified_bboxes,
                    verification_passed=verification_passed,
                    corrections_made=corrections_made,
                    verification_notes=verification_notes
                )

                page_results.append(page_verified.model_dump())
                total_corrections += corrections_made

                # Accumulate metrics
                total_cost += cost
                total_prompt_tokens += usage.get("prompt_tokens", 0)
                total_completion_tokens += usage.get("completion_tokens", 0)
                reasoning_details = usage.get("completion_tokens_details", {})
                total_reasoning_tokens += reasoning_details.get("reasoning_tokens", 0)

                # Record page-level metrics
                stage_storage_obj = storage.stage('extract-toc')
                stage_storage_obj.metrics_manager.record(
                    key=f"phase3_page_{page_num:04d}",
                    cost_usd=cost,
                    time_seconds=page_time,
                    custom_metrics={
                        "phase": "bbox_verification",
                        "page": page_num,
                        "verification_passed": verification_passed,
                        "corrections_made": corrections_made,
                        "final_bbox_count": len(verified_bboxes),
                        "prompt_tokens": usage.get("prompt_tokens", 0),
                        "completion_tokens": usage.get("completion_tokens", 0),
                        "reasoning_tokens": reasoning_details.get("reasoning_tokens", 0),
                    }
                )

                # Update progress with completion
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)
                reasoning_tokens = reasoning_details.get("reasoning_tokens", 0)

                status_icon = "✓" if verification_passed else "⚠"
                result_summary = f"{status_icon} {corrections_made} corrections | {len(verified_bboxes)} boxes | {page_time:.1f}s | {prompt_tokens}in→{completion_tokens}out+{reasoning_tokens}r | ${cost:.4f}"
                progress.complete_page(page_num, result_summary)

            except Exception as e:
                logger.error(f"    ✗ Failed to verify page {page_num}: {e}")
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
        "total_corrections": total_corrections,
    }

    return results_data, metrics


def _draw_bboxes_on_image(image: Image.Image, bboxes: List[BoundingBox]) -> Image.Image:
    """
    Draw bounding boxes on image for visualization.

    Returns a copy of the image with red boxes drawn.
    """
    img_copy = image.copy()
    draw = ImageDraw.Draw(img_copy)

    for bbox in bboxes:
        # Draw red rectangle
        left = bbox.x
        top = bbox.y
        right = bbox.x + bbox.width
        bottom = bbox.y + bbox.height

        draw.rectangle([left, top, right, bottom], outline="red", width=2)

    return img_copy


def _apply_corrections(
    original_bboxes: List[BoundingBox],
    corrections: List[Dict]
) -> List[BoundingBox]:
    """
    Apply corrections to bbox list.

    Handles: add, remove, adjust actions
    """
    result_bboxes = original_bboxes.copy()

    for correction in corrections:
        action = correction.get("action")

        if action == "add":
            # Add new bbox
            bbox_data = correction.get("bbox", {})
            new_bbox = BoundingBox(
                x=bbox_data.get("x", 0),
                y=bbox_data.get("y", 0),
                width=bbox_data.get("width", 0),
                height=bbox_data.get("height", 0)
            )
            result_bboxes.append(new_bbox)

        elif action == "remove":
            # Remove bbox by index (convert to int if string from JSON)
            bbox_index = correction.get("bbox_index")
            if bbox_index is not None:
                try:
                    bbox_index = int(bbox_index)
                    if 0 <= bbox_index < len(result_bboxes):
                        result_bboxes.pop(bbox_index)
                except (ValueError, TypeError):
                    pass  # Invalid index, skip

        elif action == "adjust":
            # Adjust existing bbox (convert to int if string from JSON)
            bbox_index = correction.get("bbox_index")
            bbox_data = correction.get("bbox", {})
            if bbox_index is not None:
                try:
                    bbox_index = int(bbox_index)
                    if 0 <= bbox_index < len(result_bboxes):
                        result_bboxes[bbox_index] = BoundingBox(
                            x=bbox_data.get("x", result_bboxes[bbox_index].x),
                            y=bbox_data.get("y", result_bboxes[bbox_index].y),
                            width=bbox_data.get("width", result_bboxes[bbox_index].width),
                            height=bbox_data.get("height", result_bboxes[bbox_index].height)
                        )
                except (ValueError, TypeError, IndexError):
                    pass  # Invalid index, skip

    return result_bboxes
