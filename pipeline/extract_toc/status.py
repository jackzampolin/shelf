import time
from enum import Enum
from typing import Dict, Any

from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger

from .storage import ExtractTocStageStorage


class ExtractTocStatus(str, Enum):
    NOT_STARTED = "not_started"
    FINDING_TOC = "finding_toc"
    EXTRACTING_STRUCTURE = "extracting_structure"
    GENERATING_TOC_DRAFT = "generating_toc_draft"
    CHECKING_TOC = "checking_toc"
    MERGING_TOC = "merging_toc"
    COMPLETED = "completed"


class ExtractTocStatusTracker:

    def __init__(self, stage_name: str):
        self.stage_name = stage_name
        self.storage = ExtractTocStageStorage(stage_name=stage_name)

    def get_progress(
        self,
        storage: BookStorage,
        logger: PipelineLogger
    ) -> Dict[str, Any]:

        finder_result_exists = self.storage.finder_result_exists(storage)
        structure_exists = self.storage.structure_exists(storage)
        toc_unchecked_exists = self.storage.toc_unchecked_exists(storage)
        toc_diff_exists = self.storage.toc_diff_exists(storage)
        toc_final_exists = self.storage.toc_final_exists(storage)

        if not finder_result_exists:
            status = ExtractTocStatus.FINDING_TOC.value
        elif not structure_exists:
            status = ExtractTocStatus.EXTRACTING_STRUCTURE.value
        elif not toc_unchecked_exists:
            status = ExtractTocStatus.GENERATING_TOC_DRAFT.value
        elif not toc_diff_exists:
            status = ExtractTocStatus.CHECKING_TOC.value
        elif not toc_final_exists:
            status = ExtractTocStatus.MERGING_TOC.value
        else:
            status = ExtractTocStatus.COMPLETED.value

        stage_storage_obj = storage.stage(self.stage_name)
        all_metrics = stage_storage_obj.metrics_manager.get_all()

        total_cost = sum(m.get('cost_usd', 0.0) for m in all_metrics.values())
        total_time = stage_storage_obj.metrics_manager.get_total_time()

        return {
            "status": status,
            "metrics": {
                "total_cost_usd": total_cost,
                "total_time_seconds": total_time,
            },
            "artifacts": {
                "finder_result_exists": finder_result_exists,
                "structure_exists": structure_exists,
                "toc_unchecked_exists": toc_unchecked_exists,
                "toc_diff_exists": toc_diff_exists,
                "toc_final_exists": toc_final_exists,
            }
        }
