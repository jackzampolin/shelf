from .processor import (
    merge_outputs,
    get_base_merged_page,
    get_simple_fixes_merged_page,
    get_merged_page,
)
from infra.pipeline.status import page_batch_tracker

def create_tracker(stage_storage):
    return page_batch_tracker(
        stage_storage=stage_storage,
        phase_name="merge",
        run_fn=merge_outputs,
        use_subdir=False,
    )

__all__ = [
    "merge_outputs",
    "get_base_merged_page",
    "get_simple_fixes_merged_page",
    "get_merged_page",
    "create_tracker",
]
