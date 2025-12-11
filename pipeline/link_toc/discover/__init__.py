from infra.pipeline.status import artifact_tracker
from .processor import discover_pattern_entries


def create_tracker(stage_storage, model=None):
    def run_discover(tracker, **kwargs):
        return discover_pattern_entries(tracker=tracker, model=model)

    return artifact_tracker(
        stage_storage=stage_storage,
        phase_name="discover",
        artifact_filename="discover_complete.json",  # Marker file
        run_fn=run_discover,
        use_subdir=True,
        description="Search for each entry in detected patterns",
    )


__all__ = [
    "discover_pattern_entries",
    "create_tracker",
]
