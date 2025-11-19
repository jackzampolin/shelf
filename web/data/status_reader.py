"""
Read stage status directly from disk.

Avoids importing heavy Stage dependencies by reading MetricsManager
data directly from filesystem.

Ground truth from disk (ADR 001).
"""

from typing import Dict, Any, Optional
from pathlib import Path

from infra.pipeline.storage.book_storage import BookStorage


def _is_stage_completed(storage: BookStorage, stage_name: str, stage_storage) -> bool:
    """
    Check if a stage is completed based on its specific completion markers.

    Each stage has different completion criteria:
    - ocr-pages, olm-ocr, mistral-ocr, paddle-ocr: All source pages have corresponding output files
    - extract-toc: toc.json exists
    - label-pages: report.csv exists
    - label-structure: report.csv exists
    """
    # OCR stages (old and new names)
    if stage_name in ['ocr-pages', 'olm-ocr', 'mistral-ocr', 'paddle-ocr']:
        # Check if all source pages have outputs
        source_stage = storage.stage("source")
        source_pages = source_stage.list_pages(extension="png")
        total_pages = len(source_pages)

        if total_pages == 0:
            return False

        # Count completed pages
        completed = 0
        for page_num in range(1, total_pages + 1):
            page_path = stage_storage.output_dir / f"page_{page_num:04d}.json"
            if page_path.exists():
                completed += 1

        return completed == total_pages

    elif stage_name == 'extract-toc':
        # Complete when toc.json exists
        return (stage_storage.output_dir / 'toc.json').exists()

    elif stage_name == 'label-pages':
        # Complete when report.csv exists
        return (stage_storage.output_dir / 'report.csv').exists()

    elif stage_name == 'label-structure':
        # Complete when report.csv exists
        return (stage_storage.output_dir / 'report.csv').exists()

    else:
        # Unknown stage - check for report.csv as fallback
        return (stage_storage.output_dir / 'report.csv').exists()


def get_stage_status_from_disk(storage: BookStorage, stage_name: str) -> Optional[Dict[str, Any]]:
    """
    Read stage status directly from MetricsManager without instantiating Stage.

    This avoids heavy imports required by Stage classes.
    Status is read from the stage's metrics file on disk.

    Returns:
        Dict with:
        - status: str ('completed', 'in_progress', 'not_started')
        - metrics: dict (total_cost_usd, stage_runtime_seconds, etc.)
        or None if stage has no data
    """
    stage_storage = storage.stage(stage_name)

    # Check if stage directory exists
    if not stage_storage.output_dir.exists():
        return None

    # Check for completion markers (each stage has different markers)
    completed = _is_stage_completed(storage, stage_name, stage_storage)

    # Try to get metrics from MetricsManager
    total_cost = 0.0
    stage_runtime = 0.0

    try:
        metrics_manager = stage_storage.metrics_manager
        all_metrics = metrics_manager.get_all()

        if all_metrics:
            # Get stage runtime (actual batch processing time)
            # Stored as special key 'stage_runtime' with 'time_seconds' value
            runtime_metrics = metrics_manager.get("stage_runtime")
            stage_runtime = runtime_metrics.get("time_seconds", 0.0) if runtime_metrics else 0.0

            # Calculate total cost from all metrics
            for key, metrics_data in all_metrics.items():
                total_cost += metrics_data.get('cost_usd', 0.0)

    except Exception:
        # No metrics yet - that's OK, stage might be starting
        pass

    # Determine status
    # Stage is in_progress if:
    # - Directory exists with content (not just empty)
    # - Not yet completed
    if completed:
        status = 'completed'
    elif total_cost > 0 or stage_runtime > 0:
        status = 'in_progress'
    else:
        # Check if stage has any output files (indicates work started)
        has_output = False
        if stage_storage.output_dir.exists():
            # Check for any files/dirs besides logs
            contents = [
                p for p in stage_storage.output_dir.iterdir()
                if p.name != 'logs' and p.name != '.gitkeep'
            ]
            has_output = len(contents) > 0

        if has_output:
            status = 'in_progress'
        else:
            return None  # No data at all

    return {
        'status': status,
        'metrics': {
            'total_cost_usd': total_cost,
            'stage_runtime_seconds': stage_runtime,
        }
    }
