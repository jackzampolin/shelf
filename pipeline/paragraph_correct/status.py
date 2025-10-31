"""
Paragraph-Correct Stage Status Tracking

Calculates progress by checking files on disk (ground truth).
Determines what work remains to be done for resume support.
"""

from enum import Enum
from typing import Dict, Any

from infra.storage.book_storage import BookStorage
from infra.storage.checkpoint import CheckpointManager
from infra.pipeline.logger import PipelineLogger

from .storage import ParagraphCorrectStageStorage


class ParagraphCorrectStatus(str, Enum):
    """Status progression for paragraph-correct stage."""
    NOT_STARTED = "not_started"
    CORRECTING = "correcting"
    GENERATING_REPORT = "generating_report"
    COMPLETED = "completed"


class ParagraphCorrectStatusTracker:
    """
    Tracks progress by checking files on disk.

    Ground truth is what exists on disk, not what's in checkpoint.
    This enables reliable resume from any interruption point.
    """

    def __init__(self, stage_name: str):
        self.stage_name = stage_name
        self.storage = ParagraphCorrectStageStorage(stage_name=stage_name)

    def get_progress(
        self,
        storage: BookStorage,
        checkpoint: CheckpointManager,
        logger: PipelineLogger
    ) -> Dict[str, Any]:
        """
        Calculate what work remains by checking disk state.

        Returns:
            {
                "status": "correcting",
                "total_pages": 100,
                "remaining_pages": [5, 10, 23],
                "metrics": {"total_cost_usd": 1.23},
                "artifacts": {"report_exists": False}
            }
        """
        # Get total pages from metadata
        metadata = storage.load_metadata()
        total_pages = metadata.get('total_pages', 0)

        if total_pages == 0:
            raise ValueError("total_pages not set in metadata")

        # Check which pages have corrected outputs on disk (ground truth)
        completed_pages = self.storage.list_completed_pages(storage)
        remaining_pages = [
            p for p in range(1, total_pages + 1)
            if p not in completed_pages
        ]

        # Check artifacts on disk
        report_exists = self.storage.report_exists(storage)

        # Determine status based on disk state
        if len(remaining_pages) == total_pages:
            status = ParagraphCorrectStatus.NOT_STARTED.value
        elif len(remaining_pages) > 0:
            status = ParagraphCorrectStatus.CORRECTING.value
        elif not report_exists:
            status = ParagraphCorrectStatus.GENERATING_REPORT.value
        else:
            status = ParagraphCorrectStatus.COMPLETED.value

        # Calculate aggregate metrics from checkpoint
        checkpoint_state = checkpoint.get_status()
        page_metrics = checkpoint_state.get('page_metrics', {})

        total_cost = 0.0
        total_tokens = 0
        total_corrections = 0
        confidences = []

        for metrics in page_metrics.values():
            # Cost
            total_cost += metrics.get('cost_usd', 0.0)

            # Tokens (from usage dict)
            usage = metrics.get('usage', {})
            if usage:
                total_tokens += usage.get('completion_tokens', 0)
                total_tokens += usage.get('prompt_tokens', 0)

            # Quality metrics
            total_corrections += metrics.get('total_corrections', 0)

            conf = metrics.get('avg_confidence')
            if conf is not None:
                confidences.append(conf)

        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        # Get wall-clock time from checkpoint (not sum of request times due to parallelism)
        total_time = checkpoint_state.get('elapsed_time', 0.0)

        return {
            "status": status,
            "total_pages": total_pages,
            "remaining_pages": remaining_pages,
            "metrics": {
                "total_cost_usd": total_cost,
                "total_tokens": total_tokens,
                "total_time_seconds": total_time,
                "total_corrections": total_corrections,
                "avg_confidence": avg_confidence,
            },
            "artifacts": {
                "report_exists": report_exists,
            },
        }
