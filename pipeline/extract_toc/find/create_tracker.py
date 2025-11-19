"""Create tracker for find phase (locate ToC pages)."""

from infra.pipeline.status import PhaseStatusTracker
from infra.pipeline.storage.stage_storage import StageStorage


def create_find_tracker(stage_storage: StageStorage, model: str, max_attempts: int = 3):
    """
    Create the ToC finder phase tracker with automatic retry.

    Completion criteria: finder_result.json exists AND toc_found=true
    If ToC is not found, automatically retries up to max_attempts times.
    Each retry receives context from previous attempt(s).

    Args:
        stage_storage: Storage for this stage
        model: Model to use for vision/LLM calls
        max_attempts: Max number of find attempts (default: 3)
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

        # Check how many attempts we've made
        finder_result_path = stage_storage.output_dir / "finder_result.json"
        attempt_num = 1

        if finder_result_path.exists():
            try:
                import json
                with open(finder_result_path) as f:
                    previous = json.load(f)
                # Count attempts from previous runs
                attempt_num = previous.get('attempt_number', 1) + 1
            except Exception:
                pass

        # If we've exceeded max attempts, stop
        if attempt_num > max_attempts:
            tracker.logger.warning(f"Max attempts ({max_attempts}) reached - ToC not found")
            return {"status": "failed", "reason": f"ToC not found after {max_attempts} attempts"}

        if attempt_num > 1:
            tracker.logger.info(f"Retry attempt {attempt_num}/{max_attempts}")

        agent = TocFinderAgent(
            storage=tracker.storage,
            tracker=tracker,
            logger=tracker.logger,
            max_iterations=15,
            verbose=True,
            attempt_number=attempt_num
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
