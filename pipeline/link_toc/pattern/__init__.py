from .processor import analyze_toc_pattern
from infra.pipeline.status import artifact_tracker


def create_tracker(stage_storage):
    """Create the pattern analysis phase tracker."""
    return artifact_tracker(
        stage_storage=stage_storage,
        phase_name="pattern",
        artifact_filename="pattern_analysis.json",
        run_fn=analyze_toc_pattern,
        use_subdir=True,
    )


__all__ = [
    "analyze_toc_pattern",
    "create_tracker",
]
