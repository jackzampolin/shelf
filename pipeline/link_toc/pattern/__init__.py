from .processor import analyze_toc_pattern
from infra.pipeline.status import artifact_tracker


def create_tracker(stage_storage, model: str = None):
    def run_pattern_analysis(tracker, **kwargs):
        return analyze_toc_pattern(tracker=tracker, model=model)

    return artifact_tracker(
        stage_storage=stage_storage,
        phase_name="pattern",
        artifact_filename="pattern_analysis.json",
        run_fn=run_pattern_analysis,
        use_subdir=True,
        description="Analyze heading patterns to find candidates",
    )


__all__ = [
    "analyze_toc_pattern",
    "create_tracker",
]
