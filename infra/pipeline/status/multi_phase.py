from typing import Dict, Any, List, Optional
from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger


class MultiPhaseStatusTracker:
    def __init__(
        self,
        stage_name: str,
        phases: List[Dict[str, Any]]
    ):
        self.stage_name = stage_name
        self.phases = phases

    def get_status(
        self,
        storage: BookStorage,
        logger: PipelineLogger
    ) -> Dict[str, Any]:
        stage_storage = storage.stage(self.stage_name)

        completed_phases = []
        all_metrics = {}

        for phase in self.phases:
            phase_complete = self._is_phase_complete(phase, storage, logger)

            if phase_complete:
                completed_phases.append(phase["name"])

                if "tracker" in phase:
                    phase_status = phase["tracker"].get_status(storage, logger)
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

    def _is_phase_complete(
        self,
        phase: Dict[str, Any],
        storage: BookStorage,
        logger: PipelineLogger
    ) -> bool:
        if "tracker" in phase:
            phase_status = phase["tracker"].get_status(storage, logger)
            return phase_status["status"] == "completed"
        elif "artifact" in phase:
            stage_storage = storage.stage(self.stage_name)
            return (stage_storage.output_dir / phase["artifact"]).exists()
        else:
            raise ValueError(f"Phase {phase['name']} must have 'tracker' or 'artifact'")

    def _merge_metrics(self, target: Dict, source: Dict):
        for key, value in source.items():
            if key in target:
                if isinstance(value, (int, float)):
                    target[key] += value
            else:
                target[key] = value
