from .extractor import extract_mechanical_patterns
from .processor import process_mechanical_extraction
from infra.pipeline.status import page_batch_tracker


def create_tracker(stage_storage):
    return page_batch_tracker(
        stage_storage=stage_storage,
        phase_name="mechanical",
        run_fn=process_mechanical_extraction,
        use_subdir=True,
        description="Extract patterns using regex and heuristics",
    )


__all__ = [
    "extract_mechanical_patterns",
    "process_mechanical_extraction",
    "create_tracker",
]
