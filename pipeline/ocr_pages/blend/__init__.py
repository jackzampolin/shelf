from .processor import process_blend
from infra.pipeline.status import page_batch_tracker


def create_tracker(stage_storage, model: str, max_workers: int):
    return page_batch_tracker(
        stage_storage=stage_storage,
        phase_name="blend",
        run_fn=process_blend,
        use_subdir=True,
        run_kwargs={
            "model": model,
            "max_workers": max_workers,
        }
    )


__all__ = [
    "process_blend",
    "create_tracker",
]
