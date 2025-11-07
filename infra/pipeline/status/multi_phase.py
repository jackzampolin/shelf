from typing import Dict, Any, List, Optional
from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger


class MultiPhaseStatusTracker:
    def __init__(
        self,
        storage: BookStorage,
        logger: PipelineLogger,
        stage_name: str,
        phases: List[Dict[str, Any]]
    ):
        self.storage = storage
        self.logger = logger
        self.stage_name = stage_name
        self.phases = phases

    def is_completed(self) -> bool:
        """Check if all phases are completed."""
        status = self.get_status()
        return status["status"] == "completed"

    def get_skip_response(self) -> Dict[str, Any]:
        """Get response for when stage is already completed."""
        status = self.get_status()
        return {
            "status": "skipped",
            "reason": "already completed",
            "phases_completed": status["progress"]["completed_phases"]
        }

    def get_status(self) -> Dict[str, Any]:
        """Get current status by checking disk for completed phases."""
        stage_storage = self.storage.stage(self.stage_name)

        completed_phases = []
        all_metrics = {}

        for phase in self.phases:
            phase_complete = self._is_phase_complete(phase)

            if phase_complete:
                completed_phases.append(phase["name"])

                if "tracker" in phase:
                    phase_status = phase["tracker"].get_status()
                    self._merge_metrics(all_metrics, phase_status.get("metrics", {}))

        if len(completed_phases) == 0:
            status = "not_started"
        elif len(completed_phases) == len(self.phases):
            status = "completed"
        else:
            current_phase = self.phases[len(completed_phases)]
            status = f"in_progress_{current_phase['name']}"

        base_metrics = stage_storage.metrics_manager.get_aggregated()
        self._merge_metrics(all_metrics, base_metrics)

        return {
            "status": status,
            "progress": {
                "total_phases": len(self.phases),
                "completed_phases": completed_phases,
                "current_phase": self.phases[len(completed_phases)]["name"] if status.startswith("in_progress") else None,
            },
            "metrics": all_metrics,
        }

    def _is_phase_complete(self, phase: Dict[str, Any]) -> bool:
        """Check if a single phase is complete by checking tracker or artifact."""
        if "tracker" in phase:
            phase_status = phase["tracker"].get_status()
            return phase_status["status"] == "completed"
        elif "artifact" in phase:
            stage_storage = self.storage.stage(self.stage_name)
            return (stage_storage.output_dir / phase["artifact"]).exists()
        else:
            raise ValueError(f"Phase {phase['name']} must have 'tracker' or 'artifact'")

    def _merge_metrics(self, target: Dict, source: Dict):
        """Merge metrics from source into target, summing numeric values."""
        for key, value in source.items():
            if key in target:
                if isinstance(value, (int, float)):
                    target[key] += value
            else:
                target[key] = value
