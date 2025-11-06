from enum import Enum
from typing import Dict, Any

from infra.storage.book_storage import BookStorage

from .storage import LinkTocStageStorage


class LinkTocStatus(str, Enum):
    NOT_STARTED = "not_started"
    MAPPING_COMPLETE = "mapping_complete"
    COMPLETED = "completed"


class LinkTocStatusTracker:
    """Track link-toc stage status based on ground truth from disk."""

    def __init__(self, stage_name: str):
        self.stage_name = stage_name
        self.storage = LinkTocStageStorage(stage_name=stage_name)

    def get_status(
        self,
        storage: BookStorage
    ) -> Dict[str, Any]:
        """Get link-toc status from disk artifacts."""

        linked_toc_exists = self.storage.linked_toc_exists(storage)
        report_exists = self.storage.report_exists(storage)

        # Get progress
        completed_indices = self.storage.get_completed_entry_indices(storage)
        completed_count = len(completed_indices)

        # Load extract-toc to get total entry count
        try:
            extract_toc_output = self.storage.load_extract_toc_output(storage)
            toc_data = extract_toc_output.get('toc', {}) if extract_toc_output else {}
            total_entries = len(toc_data.get('entries', []))
        except:
            total_entries = 0

        # Determine status based on progress
        if completed_count == 0:
            status = LinkTocStatus.NOT_STARTED.value
        elif completed_count < total_entries:
            status = LinkTocStatus.MAPPING_COMPLETE.value  # In progress
        elif not report_exists:
            status = LinkTocStatus.MAPPING_COMPLETE.value  # Mapping done, report pending
        else:
            status = LinkTocStatus.COMPLETED.value

        # Load linked ToC statistics if available
        found_entries = 0
        not_found_entries = 0
        avg_confidence = 0.0

        if linked_toc_exists:
            linked_toc = self.storage.load_linked_toc(storage)
            if linked_toc:
                # Filter out None entries
                real_entries = [e for e in linked_toc.entries if e is not None]
                found_entries = sum(1 for e in real_entries if e.scan_page is not None)
                not_found_entries = len(real_entries) - found_entries

                # Compute average confidence from actual entries
                linked_only = [e for e in real_entries if e.scan_page is not None]
                avg_confidence = (
                    sum(e.link_confidence for e in linked_only) / len(linked_only)
                    if linked_only else 0.0
                )

        # Aggregate metrics
        stage_storage = storage.stage(self.stage_name)
        all_metrics = stage_storage.metrics_manager.get_all()

        total_cost = 0.0
        total_time = 0.0

        for metrics in all_metrics.values():
            total_cost += metrics.get('cost_usd', 0.0)
            total_time += metrics.get('time_seconds', 0.0)

        runtime_metrics = stage_storage.metrics_manager.get("stage_runtime")
        stage_runtime = runtime_metrics.get("time_seconds", 0.0) if runtime_metrics else 0.0

        return {
            "status": status,
            "total_entries": total_entries,
            "completed_entries": completed_count,
            "found_entries": found_entries,
            "not_found_entries": not_found_entries,
            "avg_confidence": avg_confidence,
            "metrics": {
                "total_cost_usd": total_cost,
                "total_time_seconds": total_time,
                "stage_runtime_seconds": stage_runtime,
            },
            "artifacts": {
                "linked_toc_exists": linked_toc_exists,
                "report_exists": report_exists,
            },
        }
