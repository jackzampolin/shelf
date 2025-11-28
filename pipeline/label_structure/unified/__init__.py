from .processor import process_unified_extraction
from infra.pipeline.status import page_batch_tracker


def create_tracker(stage_storage, model: str, max_workers: int):
    """Create the unified structure + annotations extraction phase tracker."""
    return page_batch_tracker(
        stage_storage=stage_storage,
        phase_name="unified",
        run_fn=process_unified_extraction,
        use_subdir=True,
        run_kwargs={
            "model": model,
            "max_workers": max_workers,
        }
    )


__all__ = [
    "process_unified_extraction",
    "create_tracker",
]
