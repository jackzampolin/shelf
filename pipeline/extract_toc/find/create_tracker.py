"""Create tracker for find phase (locate ToC pages)."""

import os

from infra.pipeline.status import PhaseStatusTracker
from infra.pipeline.storage.stage_storage import StageStorage


def is_headless():
    """Check if running in headless mode (no Rich Live displays)."""
    return os.environ.get('SCANSHELF_HEADLESS', '').lower() in ('1', 'true', 'yes')


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

        # Loop for automatic retry within same run
        for attempt_num in range(1, max_attempts + 1):
            if attempt_num > 1:
                tracker.logger.info(f"Retry attempt {attempt_num}/{max_attempts}")

            agent = TocFinderAgent(
                storage=tracker.storage,
                tracker=tracker,
                logger=tracker.logger,
                max_iterations=15,
                verbose=not is_headless(),
                attempt_number=attempt_num
            )
            result = agent.search()

            # Check if ToC was found
            finder_result_path = stage_storage.output_dir / "finder_result.json"
            if finder_result_path.exists():
                try:
                    import json
                    with open(finder_result_path) as f:
                        finder_result = json.load(f)
                    if finder_result.get("toc_found"):
                        # Success! Return
                        return result
                except Exception:
                    pass

            # ToC not found, continue to next attempt
            if attempt_num < max_attempts:
                tracker.logger.info(f"ToC not found on attempt {attempt_num}, retrying...")

        # All attempts exhausted
        tracker.logger.warning(f"ToC not found after {max_attempts} attempts")
        return {"status": "failed", "reason": f"ToC not found after {max_attempts} attempts"}

    return PhaseStatusTracker(
        stage_storage=stage_storage,
        phase_name="find",
        discoverer=lambda phase_dir: ["finder_result.json"],
        output_path_fn=lambda item, phase_dir: phase_dir / item,
        run_fn=run_find_toc,
        use_subdir=False,
        validator_override=validate_toc_found,
    )
