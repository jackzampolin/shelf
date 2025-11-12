from typing import Dict, Any, List

from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.pipeline.status.batch_based import BatchBasedStatusTracker
from infra.llm.batch import LLMBatchProcessor, LLMBatchConfig

from .request_builder import prepare_stage1_request
from .result_handler import create_stage1_handler


def process_pages(
    storage: BookStorage,
    logger: PipelineLogger,
    stage_name: str,
    output_schema: type,
    remaining_pages: List[int],
    model: str,
    max_workers: int,
    max_retries: int
) -> Dict[str, Any]:
    """
    Process remaining pages using LLMBatchProcessor.

    Processor automatically gets items from tracker and injects storage/model.
    Stage-specific kwargs (like total_pages) are forwarded to request_builder.
    """

    logger.info(f"=== Label-Pages: Structural Analysis (3 images per page) ===")

    # Get total pages for context (stage-specific requirement)
    metadata = storage.load_metadata()
    total_pages = metadata.get('total_pages', 0)

    # Setup tracker, handler, and config
    tracker = BatchBasedStatusTracker(storage, logger, stage_name, "page_{:04d}.json")
    handler = create_stage1_handler(storage, logger, stage_name, output_schema, model)

    config = LLMBatchConfig(
        tracker=tracker,
        model=model,
        batch_name=stage_name,
        request_builder=prepare_stage1_request,
        result_handler=handler,
        max_workers=max_workers,
        max_retries=max_retries,
    )

    # Process batch - processor handles items, storage, model automatically
    processor = LLMBatchProcessor(config)
    batch_stats = processor.process(
        total_pages=total_pages,  # Stage-specific kwarg forwarded to request_builder
    )

    return batch_stats
