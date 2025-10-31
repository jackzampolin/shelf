from enum import Enum
from typing import Dict, Any

from infra.storage.book_storage import BookStorage
from infra.storage.checkpoint import CheckpointManager
from infra.pipeline.logger import PipelineLogger

from .storage import LabelPagesStageStorage


class LabelPagesStatus(str, Enum):
    NOT_STARTED = "not_started"
    LABELING = "labeling"
    GENERATING_REPORT = "generating_report"
    COMPLETED = "completed"


class LabelPagesStatusTracker:
    def __init__(self, stage_name: str):
        self.stage_name = stage_name
        self.storage = LabelPagesStageStorage(stage_name=stage_name)

    def get_progress(
        self,
        storage: BookStorage,
        checkpoint: CheckpointManager,
        logger: PipelineLogger
    ) -> Dict[str, Any]:

        metadata = storage.load_metadata()
        total_pages = metadata.get('total_pages', 0)

        if total_pages == 0:
            raise ValueError("total_pages not set in metadata")

        completed_pages = self.storage.list_completed_pages(storage)
        remaining_pages = [
            p for p in range(1, total_pages + 1)
            if p not in completed_pages
        ]

        report_exists = self.storage.report_exists(storage)

        if len(remaining_pages) == total_pages:
            status = LabelPagesStatus.NOT_STARTED.value
        elif len(remaining_pages) > 0:
            status = LabelPagesStatus.LABELING.value
        elif not report_exists:
            status = LabelPagesStatus.GENERATING_REPORT.value
        else:
            status = LabelPagesStatus.COMPLETED.value

        checkpoint_state = checkpoint.get_status()
        page_metrics = checkpoint_state.get('page_metrics', {})

        total_cost = 0.0
        total_tokens = 0
        total_blocks_classified = 0
        classification_confidences = []
        pages_with_numbers = 0
        pages_with_regions = 0

        for metrics in page_metrics.values():
            total_cost += metrics.get('cost_usd', 0.0)

            usage = metrics.get('usage', {})
            if usage:
                total_tokens += usage.get('completion_tokens', 0)
                total_tokens += usage.get('prompt_tokens', 0)

            total_blocks_classified += metrics.get('total_blocks_classified', 0)

            conf = metrics.get('avg_classification_confidence')
            if conf is not None:
                classification_confidences.append(conf)

            if metrics.get('page_number_extracted'):
                pages_with_numbers += 1

            if metrics.get('page_region_classified'):
                pages_with_regions += 1

        avg_classification_confidence = (
            sum(classification_confidences) / len(classification_confidences)
            if classification_confidences else 0.0
        )

        total_time = checkpoint_state.get('elapsed_time', 0.0)

        return {
            "status": status,
            "total_pages": total_pages,
            "remaining_pages": remaining_pages,
            "metrics": {
                "total_cost_usd": total_cost,
                "total_tokens": total_tokens,
                "total_time_seconds": total_time,
                "total_blocks_classified": total_blocks_classified,
                "avg_classification_confidence": avg_classification_confidence,
                "pages_with_numbers": pages_with_numbers,
                "pages_with_regions": pages_with_regions,
            },
            "artifacts": {
                "report_exists": report_exists,
            },
        }
