from pathlib import Path
from typing import Optional, Dict, Any
import json

from .orchestrator import heal_all_clusters
from infra.pipeline.status import PhaseStatusTracker


def _cluster_tracker(
    stage_storage,
    phase_name: str,
    run_fn,
    run_kwargs: Optional[Dict[str, Any]] = None,
) -> PhaseStatusTracker:
    def discover_clusters(phase_dir: Path):
        clusters_path = phase_dir.parent / "gap_analysis" / "clusters.json"
        if not clusters_path.exists():
            return []

        with open(clusters_path, 'r') as f:
            data = json.load(f)

        return [cluster['cluster_id'] for cluster in data.get('clusters', [])]

    return PhaseStatusTracker(
        stage_storage=stage_storage,
        phase_name=phase_name,
        discoverer=discover_clusters,
        output_path_fn=lambda cluster_id, phase_dir: phase_dir / f"cluster_{cluster_id}.json",
        run_fn=run_fn,
        use_subdir=True,
        run_kwargs=run_kwargs,
        description="Fix classification gaps using LLM agent",
    )


def create_agent_healing_tracker(stage_storage, model: str, max_workers: int):
    return _cluster_tracker(
        stage_storage=stage_storage,
        phase_name="agent_healing",
        run_fn=heal_all_clusters,
        run_kwargs={
            "model": model,
            "max_iterations": 15,
            "max_workers": max_workers,
        }
    )


__all__ = [
    "heal_all_clusters",
    "create_agent_healing_tracker",
]
