from enum import Enum
from typing import Dict, Any

from infra.storage.book_storage import BookStorage

from .storage import LabelPagesStageStorage


class LabelPagesStatus(str, Enum):
    NOT_STARTED = "not_started"
    LABELING_STAGE1 = "labeling_stage1"
    LABELING_STAGE2 = "labeling_stage2"
    GENERATING_REPORT = "generating_report"
    COMPLETED = "completed"


class LabelPagesStatusTracker:
    def __init__(self, stage_name: str):
        self.stage_name = stage_name
        self.storage = LabelPagesStageStorage(stage_name=stage_name)

    def get_status(
        self,
        storage: BookStorage
    ) -> Dict[str, Any]:
        metadata = storage.load_metadata()
        total_pages = metadata.get('total_pages', 0)

        if total_pages == 0:
            raise ValueError("total_pages not set in metadata")

        stage1_completed = self.storage.list_stage1_completed_pages(storage)
        stage2_completed = self.storage.list_completed_pages(storage)

        stage1_remaining = [
            p for p in range(1, total_pages + 1)
            if p not in stage1_completed
        ]
        stage2_remaining = [
            p for p in range(1, total_pages + 1)
            if p not in stage2_completed
        ]

        report_exists = self.storage.report_exists(storage)

        if len(stage1_remaining) == total_pages:
            status = LabelPagesStatus.NOT_STARTED.value
        elif len(stage1_remaining) > 0:
            status = LabelPagesStatus.LABELING_STAGE1.value
        elif len(stage2_remaining) > 0:
            status = LabelPagesStatus.LABELING_STAGE2.value
        elif not report_exists:
            status = LabelPagesStatus.GENERATING_REPORT.value
        else:
            status = LabelPagesStatus.COMPLETED.value

        stage_storage = storage.stage(self.stage_name)
        all_metrics = stage_storage.metrics_manager.get_all()

        stage1_cost = 0.0
        stage2_cost = 0.0
        stage1_tokens = 0
        stage2_tokens = 0
        total_blocks_classified = 0
        classification_confidences = []
        pages_with_numbers = 0
        pages_with_regions = 0

        for metrics in all_metrics.values():
            cost = metrics.get('cost_usd', 0.0)
            stage = metrics.get('stage')

            if stage == 'stage1':
                stage1_cost += cost
                usage = metrics.get('usage', {})
                if usage:
                    stage1_tokens += usage.get('completion_tokens', 0)
                    stage1_tokens += usage.get('prompt_tokens', 0)
            else:
                stage2_cost += cost
                usage = metrics.get('usage', {})
                if usage:
                    stage2_tokens += usage.get('completion_tokens', 0)
                    stage2_tokens += usage.get('prompt_tokens', 0)

                total_blocks_classified += metrics.get('total_blocks_classified', 0)

                conf = metrics.get('avg_classification_confidence')
                if conf is not None:
                    classification_confidences.append(conf)

                if metrics.get('page_number_extracted'):
                    pages_with_numbers += 1

                if metrics.get('page_region_classified'):
                    pages_with_regions += 1

        total_cost = stage1_cost + stage2_cost
        total_tokens = stage1_tokens + stage2_tokens

        avg_classification_confidence = (
            sum(classification_confidences) / len(classification_confidences)
            if classification_confidences else 0.0
        )

        total_time = stage_storage.metrics_manager.get_total_time()

        # Get stored runtime from stage execution (actual wall-clock processing time)
        # This is the actual time spent processing, excluding gaps/interruptions
        # Shows 0.0 until the stage has been run with runtime tracking enabled
        runtime_metrics = stage_storage.metrics_manager.get("stage_runtime")
        stage_runtime = runtime_metrics.get("time_seconds", 0.0) if runtime_metrics else 0.0

        return {
            "status": status,
            "total_pages": total_pages,
            "stage1_remaining": stage1_remaining,
            "stage2_remaining": stage2_remaining,
            "remaining_pages": stage2_remaining,
            "metrics": {
                "stage1_cost_usd": stage1_cost,
                "stage2_cost_usd": stage2_cost,
                "stage1_tokens": stage1_tokens,
                "stage2_tokens": stage2_tokens,
                "total_cost_usd": total_cost,
                "total_tokens": total_tokens,
                "total_time_seconds": total_time,
                "stage_runtime_seconds": stage_runtime,
                "total_blocks_classified": total_blocks_classified,
                "avg_classification_confidence": avg_classification_confidence,
                "pages_with_numbers": pages_with_numbers,
                "pages_with_regions": pages_with_regions,
            },
            "artifacts": {
                "report_exists": report_exists,
            },
        }
