from .processor import merge_enriched_toc
from infra.pipeline.status import artifact_tracker


def create_tracker(stage_storage):
    """Create the merge phase tracker."""
    return artifact_tracker(
        stage_storage=stage_storage,
        phase_name="merge",
        artifact_filename="enriched_toc.json",
        run_fn=merge_enriched_toc,
        use_subdir=False,  # Output at stage root for easy access by UI
    )


__all__ = [
    "merge_enriched_toc",
    "create_tracker",
]
