from pathlib import Path
from typing import Optional, Dict, Any
import json

from .processor import heal_page_number_gaps
from .orchestrator import heal_all_clusters
from .apply import apply_healing_decisions, extract_chapter_markers
from .clustering import create_clusters
from infra.pipeline.status import artifact_tracker, PhaseStatusTracker


def healing_directory_tracker(
    stage_storage,
    phase_name: str,
    run_fn,
    run_kwargs: Optional[Dict[str, Any]] = None,
) -> PhaseStatusTracker:
    def discover_clusters(phase_dir: Path):
        clusters_path = phase_dir.parent / "clusters" / "clusters.json"
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
    )


def create_simple_gap_healing_tracker(stage_storage):
    return artifact_tracker(
        stage_storage=stage_storage,
        phase_name="simple_gap_healing",
        artifact_filename="summary.json",
        run_fn=heal_page_number_gaps,
        use_subdir=True,
    )


def create_clusters_tracker(stage_storage):
    return artifact_tracker(
        stage_storage=stage_storage,
        phase_name="clusters",
        artifact_filename="clusters.json",
        run_fn=create_clusters,
        use_subdir=True,
    )


def create_agent_healing_tracker(stage_storage, model: str, max_workers: int):
    return healing_directory_tracker(
        stage_storage=stage_storage,
        phase_name="agent_healing",
        run_fn=heal_all_clusters,
        run_kwargs={
            "model": model,
            "max_iterations": 15,
            "max_workers": max_workers,
        }
    )


def create_healing_applied_tracker(stage_storage):
    return artifact_tracker(
        stage_storage=stage_storage,
        phase_name="healing_applied",
        artifact_filename="healing_applied.json",
        run_fn=apply_healing_decisions,
    )


def create_chapters_tracker(stage_storage):
    return artifact_tracker(
        stage_storage=stage_storage,
        phase_name="chapters_discovered",
        artifact_filename="discovered_chapters.json",
        run_fn=extract_chapter_markers,
    )


__all__ = [
    "heal_page_number_gaps",
    "heal_all_clusters",
    "apply_healing_decisions",
    "extract_chapter_markers",
    "create_simple_gap_healing_tracker",
    "create_clusters_tracker",
    "create_agent_healing_tracker",
    "create_healing_applied_tracker",
    "create_chapters_tracker",
]
