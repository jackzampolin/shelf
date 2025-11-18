"""Create tracker for validation phase."""

from infra.pipeline.status import artifact_tracker
from infra.pipeline.storage.stage_storage import StageStorage


def create_validation_tracker(stage_storage: StageStorage, model: str, max_iterations: int = None):
    """Create the ToC validation phase tracker.

    Note: max_iterations parameter is ignored (kept for backward compatibility).
    Validation now uses a single LLM call instead of multi-iteration agent.
    """
    from .processor import validate_toc_with_structure

    return artifact_tracker(
        stage_storage=stage_storage,
        phase_name="validation",
        artifact_filename="corrections.json",
        run_fn=validate_toc_with_structure,
        run_kwargs={
            "model": model,
        }
    )
