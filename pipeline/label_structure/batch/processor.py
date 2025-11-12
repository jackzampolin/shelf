from typing import Dict, Any

from infra.llm.batch import LLMBatchProcessor, LLMBatchConfig
from infra.pipeline.status import BatchBasedStatusTracker

from .request_builder import prepare_structure_extraction_request
from .result_handler import create_result_handler


def process_pages(
    tracker: BatchBasedStatusTracker,
    model: str,
    max_workers: int,
    max_retries: int,
) -> Dict[str, Any]:
    """
    Process pages using batch LLM extraction.

    Processor automatically gets items from tracker and injects storage/model.
    """
    tracker.logger.info(f"=== Label-Structure: Extract structure from multi-OCR ===")
    tracker.logger.info(f"Extraction model: {model}")

    return LLMBatchProcessor(LLMBatchConfig(
        tracker=tracker,
        model=model,
        batch_name="label-structure",
        request_builder=prepare_structure_extraction_request,
        result_handler=create_result_handler(
            tracker.storage,
            tracker.logger,
        ),
        max_workers=max_workers,
        max_retries=max_retries,
    )).process()  # Processor handles everything internally!
