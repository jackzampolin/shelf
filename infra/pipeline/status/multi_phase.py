from typing import Dict, Any, List
from infra.pipeline.storage.stage_storage import StageStorage
from .phase_tracker import PhaseStatusTracker


class MultiPhaseStatusTracker:
    def __init__(
        self,
        stage_storage: StageStorage,
        phase_trackers: List[PhaseStatusTracker]
    ):
        self.stage_storage = stage_storage
        self.logger = stage_storage.logger()
        self.phase_trackers = phase_trackers

    def is_completed(self) -> bool:
        return all(tracker.is_completed() for tracker in self.phase_trackers)

    def get_phase_metrics(self, details: bool = False) -> Dict[str, Any]:
        if details:
            return {
                tracker.phase_name: tracker.get_phase_metrics()
                for tracker in self.phase_trackers
            }
        else:
            all_metrics = {}
            for tracker in self.phase_trackers:
                phase_metrics = tracker.get_phase_metrics()
                self._merge_metrics(all_metrics, phase_metrics)
            return all_metrics

    def get_status(self, metrics: bool = False) -> Dict[str, Any]:
        completed_phases = []
        all_metrics = {}

        for tracker in self.phase_trackers:
            if tracker.is_completed():
                completed_phases.append(tracker.phase_name)

                if metrics:
                    phase_metrics = tracker.get_phase_metrics()
                    self._merge_metrics(all_metrics, phase_metrics)

        if len(completed_phases) == 0:
            status = "not_started"
        elif len(completed_phases) == len(self.phase_trackers):
            status = "completed"
        else:
            current_tracker = self.phase_trackers[len(completed_phases)]
            status = f"in_progress_{current_tracker.phase_name}"

        result = {
            "status": status,
            "progress": {
                "total_phases": len(self.phase_trackers),
                "completed_phases": completed_phases,
                "current_phase": self.phase_trackers[len(completed_phases)].phase_name if status.startswith("in_progress") else None,
            },
        }

        if metrics:
            stage_metrics = self.stage_storage.metrics_manager.get_aggregated()
            self._merge_metrics(all_metrics, stage_metrics)
            result["metrics"] = all_metrics

        return result

    def _merge_metrics(self, target: Dict, source: Dict):
        for key, value in source.items():
            if key in target:
                if isinstance(value, (int, float)):
                    target[key] += value
            else:
                target[key] = value
