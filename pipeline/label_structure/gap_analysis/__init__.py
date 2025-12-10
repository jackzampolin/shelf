from .processor import analyze_gaps
from infra.pipeline.status import artifact_tracker


def create_tracker(stage_storage):
    return artifact_tracker(
        stage_storage=stage_storage,
        phase_name="gap_analysis",
        artifact_filename="clusters.json",
        run_fn=analyze_gaps,
        use_subdir=True,
        description="Identify pages with missing or uncertain labels",
    )


__all__ = ["analyze_gaps", "create_tracker"]
