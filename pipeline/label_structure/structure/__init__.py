from .processor import process_structural_metadata
from infra.pipeline.status import page_batch_tracker


def create_tracker(stage_storage, model: str, max_workers: int):
    """Create the structural metadata extraction phase tracker."""
    return page_batch_tracker(
        stage_storage=stage_storage,
        phase_name="structure",
        run_fn=process_structural_metadata,
        use_subdir=True,
        run_kwargs={
            "model": model,
            "max_workers": max_workers,
        }
    )


__all__ = [
    "process_structural_metadata",
    "create_tracker",
]
