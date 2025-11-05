import time
from enum import Enum
from typing import Dict, Any

from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger

from .storage import ExtractTocStageStorage


class ExtractTocStatus(str, Enum):
    NOT_STARTED = "not_started"
    OCR_TEXT = "ocr_text"
    IDENTIFY_ELEMENTS = "identify_elements"
    VALIDATING = "validating"
    COMPLETED = "completed"


class ExtractTocStatusTracker:

    def __init__(self, stage_name: str):
        self.stage_name = stage_name
        self.storage = ExtractTocStageStorage(stage_name=stage_name)

    def get_status(
        self,
        storage: BookStorage
    ) -> Dict[str, Any]:

        ocr_text_exists = self.storage.ocr_text_exists(storage)
        elements_identified_exists = self.storage.elements_identified_exists(storage)
        toc_validated_exists = self.storage.toc_validated_exists(storage)

        if not ocr_text_exists:
            status = ExtractTocStatus.OCR_TEXT.value
        elif not elements_identified_exists:
            status = ExtractTocStatus.IDENTIFY_ELEMENTS.value
        elif not toc_validated_exists:
            status = ExtractTocStatus.VALIDATING.value
        else:
            status = ExtractTocStatus.COMPLETED.value

        stage_storage_obj = storage.stage(self.stage_name)
        all_metrics = stage_storage_obj.metrics_manager.get_all()

        total_cost = sum(m.get('cost_usd', 0.0) for m in all_metrics.values())
        total_time = stage_storage_obj.metrics_manager.get_total_time()

        runtime_metrics = stage_storage_obj.metrics_manager.get("stage_runtime")
        stage_runtime = runtime_metrics.get("time_seconds", 0.0) if runtime_metrics else 0.0

        return {
            "status": status,
            "metrics": {
                "total_cost_usd": total_cost,
                "total_time_seconds": total_time,
                "stage_runtime_seconds": stage_runtime,
            },
            "artifacts": {
                "ocr_text_exists": ocr_text_exists,
                "elements_identified_exists": elements_identified_exists,
                "toc_validated_exists": toc_validated_exists,
            }
        }
