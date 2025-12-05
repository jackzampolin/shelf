from typing import List
from pathlib import Path

from .processor import evaluate_candidates
from infra.pipeline.status import PhaseStatusTracker


def _should_skip_evaluation(stage_storage) -> bool:
    try:
        pattern_data = stage_storage.load_file("pattern/pattern_analysis.json")
        if not pattern_data:
            return False
        return not pattern_data.get("requires_evaluation", True)
    except FileNotFoundError:
        return False


def _discover_candidate_indices(stage_storage) -> List[int]:
    """Return indices of candidates that need evaluation (not page numbers)."""
    try:
        pattern_data = stage_storage.load_file("pattern/pattern_analysis.json")
    except FileNotFoundError:
        return []

    if not pattern_data:
        return []

    if not pattern_data.get("requires_evaluation", True):
        return []

    candidates = pattern_data.get("candidate_headings", [])
    excluded_ranges = pattern_data.get("excluded_page_ranges", [])

    def is_excluded(page: int) -> bool:
        for ex in excluded_ranges:
            if ex.get("start_page", 0) <= page <= ex.get("end_page", 0):
                return True
        return False

    # Return indices of non-excluded candidates
    return [i for i, c in enumerate(candidates) if not is_excluded(c["scan_page"])]


def _create_validator(stage_storage):
    def validator(candidate_idx: int, phase_dir: Path) -> bool:
        if _should_skip_evaluation(stage_storage):
            return True
        return (phase_dir / f"heading_{candidate_idx:04d}.json").exists()
    return validator


def create_tracker(stage_storage, model: str = None):
    def run_evaluation(tracker, **kwargs):
        if _should_skip_evaluation(stage_storage):
            tracker.logger.info("Evaluation skipped - pattern determined no useful candidates")
            _save_skip_summary(stage_storage)
            return

        evaluate_candidates(tracker, model=model, **kwargs)
        _save_summary(tracker.stage_storage)

    return PhaseStatusTracker(
        stage_storage=stage_storage,
        phase_name="evaluation",
        discoverer=lambda phase_dir: _discover_candidate_indices(stage_storage),
        output_path_fn=lambda candidate_idx, phase_dir: phase_dir / f"heading_{candidate_idx:04d}.json",
        run_fn=run_evaluation,
        use_subdir=True,
        validator_override=_create_validator(stage_storage),
    )


def _save_skip_summary(stage_storage):
    summary = {
        "skipped": True,
        "reason": "Pattern analysis determined evaluation not needed",
        "total_evaluated": 0,
        "included": 0,
        "excluded": 0,
        "missing_searched": 0,
        "missing_found": 0,
    }
    stage_storage.save_file("evaluation/evaluation_summary.json", summary)


def _save_summary(stage_storage):
    eval_dir = stage_storage.output_dir / "evaluation"

    if not eval_dir.exists():
        return

    candidate_files = list(eval_dir.glob("heading_*.json"))
    included = 0
    excluded = 0
    for f in candidate_files:
        data = stage_storage.load_file(f"evaluation/{f.name}")
        if data and data.get("include"):
            included += 1
        else:
            excluded += 1

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
