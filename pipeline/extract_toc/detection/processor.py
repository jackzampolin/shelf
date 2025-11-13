from typing import Dict, Any

from infra.llm.batch import LLMBatchProcessor, LLMBatchConfig
from infra.pipeline.status import BatchBasedStatusTracker

from .request_builder import prepare_toc_request
from .result_handler import create_toc_handler


def process_toc_pages(
    tracker: BatchBasedStatusTracker,
    model: str,
    max_workers: int,
    max_retries: int,
) -> Dict[str, Any]:
    tracker.logger.info(f"=== Extract-ToC: Extract entries from ToC pages ===")
    return LLMBatchProcessor(LLMBatchConfig(
        tracker=tracker,
        model=model,
        batch_name="extract-toc",
        request_builder=prepare_toc_request,
        result_handler=create_toc_handler(
            tracker.storage,
            tracker.logger,
        ),
        max_workers=max_workers,
        max_retries=max_retries,
    )).process()
