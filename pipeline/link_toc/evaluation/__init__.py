from .processor import evaluate_candidates
from infra.pipeline.status import artifact_tracker


def create_tracker(stage_storage, model: str = None):
    """Create the evaluation phase tracker."""

    def run_evaluation(tracker, **kwargs):
        evaluate_candidates(tracker, model=model, **kwargs)
        _save_summary(tracker.stage_storage)

    return artifact_tracker(
        stage_storage=stage_storage,
        phase_name="evaluation",
        artifact_filename="evaluation_summary.json",
        run_fn=run_evaluation,
        use_subdir=True,
    )


def _save_summary(stage_storage):
    """Save evaluation summary after processing."""
    eval_dir = stage_storage.output_dir / "evaluation"

    if not eval_dir.exists():
        return

    # Count candidate heading evaluations
    candidate_files = list(eval_dir.glob("heading_*.json"))
    included = 0
    excluded = 0
    for f in candidate_files:
        data = stage_storage.load_file(f"evaluation/{f.name}")
        if data and data.get("include"):
            included += 1
        else:
            excluded += 1

    # Count missing heading searches
    missing_files = list(eval_dir.glob("missing_*.json"))
    missing_found = 0
    for f in missing_files:
        data = stage_storage.load_file(f"evaluation/{f.name}")
        if data and data.get("include"):
            missing_found += 1

    summary = {
        "total_evaluated": len(candidate_files),
        "included": included,
        "excluded": excluded,
        "missing_searched": len(missing_files),
        "missing_found": missing_found,
    }

    stage_storage.save_file("evaluation/evaluation_summary.json", summary)


__all__ = [
    "evaluate_candidates",
    "create_tracker",
]
