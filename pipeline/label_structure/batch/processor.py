from typing import Dict, Any

from infra.llm.batch import LLMBatchProcessor, LLMBatchConfig
from infra.pipeline.status import BatchBasedStatusTracker

from .request_builder import prepare_structure_extraction_request
from .result_handler import create_result_handler
from ..schemas.page_output import LabelStructurePageOutput


def process_pages(
    tracker: BatchBasedStatusTracker,
    model: str,
    max_workers: int,
    max_retries: int,
) -> Dict[str, Any]:
    remaining_pages = tracker.get_remaining_items()

    tracker.logger.info(f"=== Label-Structure: Extract structure from multi-OCR ===")
    tracker.logger.info(f"Remaining: {len(remaining_pages)} pages")
    tracker.logger.info(f"Extraction model: {model}")

    # Setup handler and config
    handler = create_result_handler(
        tracker.storage,
        tracker.logger,
        tracker.stage_name,
        LabelStructurePageOutput,
        model,
    )

    config = LLMBatchConfig(
        tracker=tracker,
        model=model,
        batch_name="label-structure",
        request_builder=prepare_structure_extraction_request,
        result_handler=handler,
        max_workers=max_workers,
        max_retries=max_retries,
    )

    processor = LLMBatchProcessor(config)
    batch_stats = processor.process(
        items=remaining_pages,
        storage=tracker.storage,
        model=model,
    )

    return batch_stats
