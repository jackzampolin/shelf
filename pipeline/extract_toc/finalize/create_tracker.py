"""Create tracker for finalize phase."""

from infra.pipeline.status import artifact_tracker
from infra.pipeline.storage.stage_storage import StageStorage


def create_finalize_tracker(stage_storage: StageStorage):
    """Create the finalize phase tracker."""

    from .processor import apply_corrections

    return artifact_tracker(
        stage_storage=stage_storage,
        phase_name="finalize",
        artifact_filename="toc.json",
        run_fn=apply_corrections,
    )
