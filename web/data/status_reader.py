"""
Read stage status using the same mechanism as CLI.

Uses stage.get_status() for accurate status - same source of truth as CLI.
Ground truth from disk (ADR 001).
"""

from typing import Dict, Any, Optional

from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.registry import get_stage_instance


def get_stage_status_from_disk(storage: BookStorage, stage_name: str) -> Optional[Dict[str, Any]]:
    """
    Get stage status by instantiating the stage and calling get_status().

    This uses the same mechanism as the CLI, ensuring consistent status
    reporting between web UI and command line.

    Returns:
        Dict with:
        - status: str ('completed', 'in_progress', 'not_started', etc.)
        - metrics: dict (total_cost_usd, stage_runtime_seconds, etc.)
        or None if stage doesn't exist
    """
    stage = None
    try:
        stage = get_stage_instance(storage, stage_name)
        status = stage.get_status(metrics=True)

        # Extract metrics from status
        status_metrics = status.get('metrics', {})
        total_cost = status_metrics.get('total_cost_usd', 0.0)
        stage_runtime = status_metrics.get('stage_runtime_seconds', 0.0)

        return {
            'status': status.get('status', 'not_started'),
            'metrics': {
                'total_cost_usd': total_cost,
                'stage_runtime_seconds': stage_runtime,
            }
        }
    except ValueError:
        # Stage not found in registry
        return None
    except Exception:
        # Stage exists but failed to get status
        return None
    finally:
        if stage is not None:
            try:
                stage.logger.close()
            except Exception:
                pass
