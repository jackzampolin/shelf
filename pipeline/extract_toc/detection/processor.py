from typing import Dict, Any

from infra.llm.batch import LLMBatchProcessor, LLMBatchConfig
from infra.pipeline.status import PhaseStatusTracker

from .request_builder import prepare_toc_request
from .result_handler import create_toc_handler


def process_toc_pages(
    tracker: PhaseStatusTracker,
    **kwargs
) -> Dict[str, Any]:
    model = kwargs.get("model")
    max_workers = kwargs.get("max_workers")
    max_retries = kwargs.get("max_retries", 5)

    tracker.logger.info(f"=== Extract-ToC: Extract entries from ToC pages ===")

    # Access book storage through tracker's stage_storage
    book_storage = tracker.stage_storage.storage

    return LLMBatchProcessor(LLMBatchConfig(
        tracker=tracker,
        model=model,
        batch_name=tracker.phase_name,
        request_builder=prepare_toc_request,
        result_handler=create_toc_handler(
            book_storage,
            tracker.logger,
            metrics_prefix=tracker.metrics_prefix,
        ),
        max_workers=max_workers,
        max_retries=max_retries,
    )).process()
