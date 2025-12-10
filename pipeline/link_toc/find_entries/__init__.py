from .processor import find_all_toc_entries
from infra.pipeline.status import artifact_tracker


def create_tracker(stage_storage, model: str, max_iterations: int, verbose: bool):
    def run_find_entries(tracker, **kwargs):
        return find_all_toc_entries(tracker=tracker, model=model, max_iterations=max_iterations, verbose=verbose)

    return artifact_tracker(
        stage_storage=stage_storage,
        phase_name="find_entries",
        artifact_filename="linked_toc.json",
        run_fn=run_find_entries,
        description="Locate each ToC entry in page content",
    )


__all__ = ["find_all_toc_entries", "create_tracker"]
