"""
Merge logic for combining margin + body + content passes.

Loads the three separate observations and combines them into
a single LabelStructurePageOutput at the root of stage storage.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from ..schemas.page_output import LabelStructurePageOutput


def merge_page_observations(
    page_num: int,
    storage: BookStorage,
    stage_name: str,
    logger: PipelineLogger,
    model: str
) -> dict:
    """
    Merge margin + body + content observations for a single page.

    Args:
        page_num: Page number to merge
        storage: BookStorage
        stage_name: Name of label-structure stage
        logger: Logger
        model: Model name for metadata

    Returns:
        Merged observation dict
    """
    stage_storage = storage.stage(stage_name)

    # Load margin observation
    margin_file = stage_storage.output_dir / "margin" / f"page_{page_num:04d}.json"
    if not margin_file.exists():
        raise FileNotFoundError(f"Margin observation not found for page {page_num}")

    with open(margin_file, 'r') as f:
        margin_data = json.load(f)

    # Load body observation
    body_file = stage_storage.output_dir / "body" / f"page_{page_num:04d}.json"
    if not body_file.exists():
        raise FileNotFoundError(f"Body observation not found for page {page_num}")

    with open(body_file, 'r') as f:
        body_data = json.load(f)

    # Load content observation
    content_file = stage_storage.output_dir / "content" / f"page_{page_num:04d}.json"
    if not content_file.exists():
        raise FileNotFoundError(f"Content observation not found for page {page_num}")

    with open(content_file, 'r') as f:
        content_data = json.load(f)

    # Calculate total cost from metrics
    margin_cost = _get_cost_from_metrics(stage_storage, f"margin_page_{page_num:04d}")
    body_cost = _get_cost_from_metrics(stage_storage, f"body_page_{page_num:04d}")
    content_cost = _get_cost_from_metrics(stage_storage, f"content_page_{page_num:04d}")
    total_cost = margin_cost + body_cost + content_cost

    # Merge into final output
    merged = {
        "scan_page_number": page_num,
        # Margin observations
        "header": margin_data.get('header', {}),
        "footer": margin_data.get('footer', {}),
        "page_number": margin_data.get('page_number', {}),
        # Body observations
        "heading": body_data.get('heading', {}),
        "whitespace": body_data.get('whitespace', {}),
        "ornamental_break": body_data.get('ornamental_break', {}),
        # Content observations
        "text_continuation": content_data.get('text_continuation', {}),
        "footnotes": content_data.get('footnotes', {}),
        # Metadata
        "model_used": model,
        "processing_cost": total_cost,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Validate against schema
    LabelStructurePageOutput(**merged)

    return merged


def _get_cost_from_metrics(stage_storage, key: str) -> float:
    """Get cost from metrics manager for a specific key."""
    try:
        metrics = stage_storage.metrics_manager.load_metrics()
        if key in metrics:
            return metrics[key].get('cost_usd', 0.0)
    except Exception:
        pass
    return 0.0


def merge_all_pages(
    storage: BookStorage,
    stage_name: str,
    logger: PipelineLogger,
    model: str,
    pages: List[int]
) -> None:
    """
    Merge observations for all pages and save to root of stage storage.

    Args:
        storage: BookStorage
        stage_name: Name of label-structure stage
        logger: Logger
        model: Model name for metadata
        pages: List of page numbers to merge
    """
    logger.info(f"=== Merging {len(pages)} page observations ===")

    stage_storage = storage.stage(stage_name)
    success_count = 0
    error_count = 0

    for page_num in pages:
        try:
            merged = merge_page_observations(
                page_num=page_num,
                storage=storage,
                stage_name=stage_name,
                logger=logger,
                model=model
            )

            # Save to root of stage storage (same as label-pages)
            stage_storage.save_page(
                page_num,
                merged,
                schema=LabelStructurePageOutput
            )

            success_count += 1
            logger.debug(f"✓ Merged page {page_num}")

        except Exception as e:
            error_count += 1
            logger.error(f"✗ Failed to merge page {page_num}: {str(e)}")

    logger.info(f"Merge complete: {success_count} success, {error_count} errors")
