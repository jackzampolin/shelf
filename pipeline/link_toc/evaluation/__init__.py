from .processor import evaluate_candidates
from infra.pipeline.status import artifact_tracker


def create_tracker(stage_storage):
    return artifact_tracker(
        stage_storage=stage_storage,
        phase_name="evaluation",
        artifact_filename="evaluation_summary.json",
        run_fn=lambda tracker, **kwargs: _run_evaluation_with_summary(tracker, **kwargs),
        use_subdir=True,
    )


def _run_evaluation_with_summary(tracker, **kwargs):
    evaluate_candidates(tracker, **kwargs)

    stage_storage = tracker.stage_storage
    eval_dir = stage_storage.output_dir / "evaluation"

    if not eval_dir.exists():
        return

    decision_files = list(eval_dir.glob("heading_*.json"))
    summary = {
        "total_evaluated": len(decision_files),
        "decisions_saved": len(decision_files)
    }

    stage_storage.save_file("evaluation/evaluation_summary.json", summary)


__all__ = [
    "evaluate_candidates",
    "create_tracker",
]
