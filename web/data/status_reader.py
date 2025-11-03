"""
Read stage status directly from disk.

Avoids importing heavy Stage dependencies (cv2, pytesseract, etc.)
by reading MetricsManager data directly from filesystem.

Ground truth from disk (ADR 001).
"""

from typing import Dict, Any, Optional
from pathlib import Path

from infra.storage.book_storage import BookStorage


def get_stage_status_from_disk(storage: BookStorage, stage_name: str) -> Optional[Dict[str, Any]]:
    """
    Read stage status directly from MetricsManager without instantiating Stage.

    This avoids heavy imports (cv2, pytesseract) required by Stage classes.
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

    # Check for completion markers first
    completed = False
    if stage_name == 'ocr':
        # OCR is complete when selection_map.json exists
        completed = (stage_storage.output_dir / 'selection_map.json').exists()
    else:
        # Other stages complete when report.csv exists
        completed = (stage_storage.output_dir / 'report.csv').exists()

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
