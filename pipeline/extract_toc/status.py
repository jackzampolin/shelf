import time
from enum import Enum
from typing import Dict, Any

from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger

from .storage import ExtractTocStageStorage


class ExtractTocStatus(str, Enum):
    NOT_STARTED = "not_started"
    FINDING_TOC = "finding_toc"
    EXTRACTING_BBOXES = "extracting_bboxes"
    VERIFYING_BBOXES = "verifying_bboxes"
    OCR_BBOXES = "ocr_bboxes"
    ASSEMBLING_TOC = "assembling_toc"
    VALIDATING_TOC = "validating_toc"
    COMPLETED = "completed"


class ExtractTocStatusTracker:

    def __init__(self, stage_name: str):
        self.stage_name = stage_name
        self.storage = ExtractTocStageStorage(stage_name=stage_name)

    def get_status(
        self,
        storage: BookStorage
    ) -> Dict[str, Any]:

        finder_result_exists = self.storage.finder_result_exists(storage)
        bboxes_extracted_exists = self.storage.bboxes_extracted_exists(storage)
        bboxes_verified_exists = self.storage.bboxes_verified_exists(storage)
        bboxes_ocr_exists = self.storage.bboxes_ocr_exists(storage)
        toc_assembled_exists = self.storage.toc_assembled_exists(storage)
        toc_validated_exists = self.storage.toc_validated_exists(storage)

        if not finder_result_exists:
            status = ExtractTocStatus.FINDING_TOC.value
        elif not bboxes_extracted_exists:
            status = ExtractTocStatus.EXTRACTING_BBOXES.value
        elif not bboxes_verified_exists:
            status = ExtractTocStatus.VERIFYING_BBOXES.value
        elif not bboxes_ocr_exists:
            status = ExtractTocStatus.OCR_BBOXES.value
        elif not toc_assembled_exists:
            status = ExtractTocStatus.ASSEMBLING_TOC.value
        elif not toc_validated_exists:
            status = ExtractTocStatus.VALIDATING_TOC.value
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
                "finder_result_exists": finder_result_exists,
                "bboxes_extracted_exists": bboxes_extracted_exists,
                "bboxes_verified_exists": bboxes_verified_exists,
                "bboxes_ocr_exists": bboxes_ocr_exists,
                "toc_assembled_exists": toc_assembled_exists,
                "toc_validated_exists": toc_validated_exists,
            }
        }
