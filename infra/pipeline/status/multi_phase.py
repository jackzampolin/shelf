from typing import Dict, Any, List, Optional
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
        # Check phases sequentially - if any phase is incomplete, stage is not complete
        for tracker in self.phase_trackers:
            if not tracker.is_completed():
                return False
        return True

    def list_phases(self) -> List[str]:
        """Return list of phase names in order."""
        return [tracker.phase_name for tracker in self.phase_trackers]

    def get_phase_tracker(self, phase_name: str) -> Optional[PhaseStatusTracker]:
        """Get a phase tracker by name."""
        for tracker in self.phase_trackers:
            if tracker.phase_name == phase_name:
                return tracker
        return None

    def clean_phase(self, phase_name: str) -> Dict[str, Any]:
        """Clean a specific phase by name."""
        tracker = self.get_phase_tracker(phase_name)
        if tracker is None:
            available = self.list_phases()
            raise ValueError(f"Phase '{phase_name}' not found. Available: {available}")
        return tracker.clean()

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

        # Check phases sequentially - stop at first incomplete phase
        # This prevents calling discoverers on later phases that depend on earlier outputs
        for tracker in self.phase_trackers:
            if tracker.is_completed():
                completed_phases.append(tracker.phase_name)

                if metrics:
                    phase_metrics = tracker.get_phase_metrics()
                    self._merge_metrics(all_metrics, phase_metrics)
            else:
                # Found incomplete phase - don't check later phases
                break

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

    def run(self) -> Dict[str, Any]:
        for phase_tracker in self.phase_trackers:
            if phase_tracker.is_completed():
                self.logger.debug(f"{phase_tracker.phase_name} phase complete, skipping")
                continue

            self.logger.info(f"Running phase: {phase_tracker.phase_name}")
            phase_tracker.run()

        return {"status": "success"}
