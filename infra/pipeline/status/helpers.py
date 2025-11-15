from typing import Any, Callable, Dict, Optional
from infra.pipeline.storage.stage_storage import StageStorage
from .phase_tracker import PhaseStatusTracker

def artifact_tracker(
    stage_storage: StageStorage,
    phase_name: str,
    artifact_filename: str,
    run_fn: Callable[[PhaseStatusTracker, Any], None],
    use_subdir: bool = False,
    run_kwargs: Optional[Dict[str, Any]] = None,
) -> PhaseStatusTracker:
    return PhaseStatusTracker(
        stage_storage=stage_storage,
        phase_name=phase_name,
        discoverer=lambda phase_dir: [artifact_filename],
        validator=lambda item, phase_dir: (phase_dir / item).exists(),
        run_fn=run_fn,
        use_subdir=use_subdir,
        run_kwargs=run_kwargs,
    )

def page_batch_tracker(
    stage_storage: StageStorage,
    phase_name: str,
    run_fn: Callable[[PhaseStatusTracker, Any], None],
    extension: str = "json",
    use_subdir: bool = False,
    run_kwargs: Optional[Dict[str, Any]] = None,
) -> PhaseStatusTracker:
    book_storage = stage_storage.storage
    source_pages = book_storage.stage("source").list_pages(extension="png")

    # Discoverer returns page numbers (integers), not filenames
    # Validator checks if the corresponding file exists
    return PhaseStatusTracker(
        stage_storage=stage_storage,
        phase_name=phase_name,
        discoverer=lambda phase_dir: source_pages,  # Returns list of ints
        validator=lambda page_num, phase_dir: (phase_dir / f"page_{page_num:04d}.{extension}").exists(),
        run_fn=run_fn,
        use_subdir=use_subdir,
        run_kwargs=run_kwargs,
    )
