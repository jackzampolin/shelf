"""Create phase tracker for Extract phase."""

from infra.pipeline.status import PhaseStatusTracker
from infra.pipeline.storage.stage_storage import StageStorage


def create_extract_tracker(
    stage_storage: StageStorage,
    model: str
) -> PhaseStatusTracker:
    """
    Create phase tracker for Extract (single-call ToC extraction).

    Completion criteria: toc.json exists with entries array

    Args:
        stage_storage: Storage for this stage
        model: LLM model to use

    Returns:
        PhaseStatusTracker configured for Extract phase
    """

    def validate_toc_extracted(item, phase_dir):
        """Check if ToC was successfully extracted."""
        toc_path = phase_dir / item
        if not toc_path.exists():
            return False

        try:
            import json
            with open(toc_path) as f:
                result = json.load(f)
            # Valid if we have entries (even if empty list means no ToC)
            return "entries" in result
        except Exception:
            return False

    def run_extract_toc(tracker, **kwargs):
        from .processor import extract_complete_toc
        return extract_complete_toc(tracker, **kwargs)

    return PhaseStatusTracker(
        stage_storage=stage_storage,
        phase_name="extract",
        discoverer=lambda phase_dir: ["toc.json"],
        output_path_fn=lambda item, phase_dir: phase_dir / item,
        run_fn=run_extract_toc,
        use_subdir=False,
        run_kwargs={"model": model},
        validator_override=validate_toc_extracted,
    )
