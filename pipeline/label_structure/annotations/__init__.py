from .processor import process_annotations
from infra.pipeline.status import page_batch_tracker


def create_tracker(stage_storage, model: str, max_workers: int):
    """Create the annotations extraction phase tracker."""
    return page_batch_tracker(
        stage_storage=stage_storage,
        phase_name="annotations",
        run_fn=process_annotations,
        use_subdir=True,
        run_kwargs={
            "model": model,
            "max_workers": max_workers,
        }
    )


__all__ = [
    "process_annotations",
    "create_tracker",
]
