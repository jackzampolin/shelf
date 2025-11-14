from typing import Callable
from infra.pipeline import StageStorage
from .phase_tracker import PhaseStatusTracker

def artifact_tracker(
    stage_storage: StageStorage,
    phase_name: str,
    artifact_filename: str,
    run_fn: Callable[[PhaseStatusTracker], None],
    use_subdir: bool = False,
) -> PhaseStatusTracker:
    return PhaseStatusTracker(
        stage_storage=stage_storage,
        phase_name=phase_name,
        discoverer=lambda phase_dir: [artifact_filename],
        validator=lambda item, phase_dir: (phase_dir / item).exists(),
        run_fn=run_fn,
        use_subdir=use_subdir,
    )

def page_batch_tracker(
    stage_storage: StageStorage,
    phase_name: str,
    run_fn: Callable[[PhaseStatusTracker], None],
    extension: str = "json",
    use_subdir: bool = False,
) -> PhaseStatusTracker:
    book_storage = stage_storage.storage
    source_pages = book_storage.stage("source").list_pages(extension="png")

    return PhaseStatusTracker(
        stage_storage=stage_storage,
        phase_name=phase_name,
        discoverer=lambda phase_dir: [f"page_{num:04d}.{extension}" for num in source_pages],
        validator=lambda item, phase_dir: (phase_dir / item).exists(),
        run_fn=run_fn,
        use_subdir=use_subdir,
    )
