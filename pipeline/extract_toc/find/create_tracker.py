"""Create tracker for find phase (locate ToC pages)."""

from infra.pipeline.status import PhaseStatusTracker
from infra.pipeline.storage.stage_storage import StageStorage


def create_find_tracker(stage_storage: StageStorage, model: str):
    """
    Create the ToC finder phase tracker.

    Completion criteria: finder_result.json exists AND toc_found=true
    If ToC is not found, phase remains incomplete (can be retried).
    On retry, previous attempt's notes are passed to agent as context.
    """

    def validate_toc_found(item, phase_dir):
        """Check if ToC was found (not just if file exists)."""
        finder_result_path = phase_dir / item
        if not finder_result_path.exists():
            return False

        # Load and check if ToC was actually found
        try:
            import json
            with open(finder_result_path) as f:
                result = json.load(f)
            return result.get("toc_found", False)
        except Exception:
            return False

    def run_find_toc(tracker, **kwargs):
        from .agent.finder import TocFinderAgent

        agent = TocFinderAgent(
            storage=tracker.storage,
            tracker=tracker,
            logger=tracker.logger,
            max_iterations=15,
            verbose=True
        )
        return agent.search()

    return PhaseStatusTracker(
        stage_storage=stage_storage,
        phase_name="find",
        discoverer=lambda phase_dir: ["finder_result.json"],
        validator=validate_toc_found,
        run_fn=run_find_toc,
        use_subdir=False,
    )
