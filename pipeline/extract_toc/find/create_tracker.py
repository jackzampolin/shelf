"""Create tracker for find phase (locate ToC pages)."""

from infra.pipeline.status import artifact_tracker
from infra.pipeline.storage.stage_storage import StageStorage


def create_find_tracker(stage_storage: StageStorage, model: str):
    """Create the ToC finder phase tracker."""

    def run_find_toc(tracker, **kwargs):
        from .agent.finder import TocFinderAgent

        agent = TocFinderAgent(
            storage=tracker.storage,
            tracker=tracker,  # Pass tracker instead of stage_storage
            logger=tracker.logger,
            max_iterations=15,
            verbose=True
        )
        return agent.search()

    return artifact_tracker(
        stage_storage=stage_storage,
        phase_name="find",
        artifact_filename="finder_result.json",
        run_fn=run_find_toc,
    )
