from typing import Dict, Any, List

from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
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
    """Process remaining pages using LLMBatchProcessor."""

    logger.info(f"=== Label-Pages: Structural Analysis (3 images per page) ===")
    logger.info(f"Remaining: {len(remaining_pages)} pages")

    # Setup processor and handler
    processor = LLMBatchProcessor(
        storage=storage,
        stage_name=stage_name,
        logger=logger,
        config=LLMBatchConfig(
            model=model,
            max_workers=max_workers,
            max_retries=max_retries,
            batch_name=stage_name
        ),
    )
    handler = create_stage1_handler(
        storage,
        logger,
        stage_name,
        output_schema,
        model
    )

    # Get total pages for context
    metadata = storage.load_metadata()
    total_pages = metadata.get('total_pages', 0)

    # Process batch
    batch_stats = processor.process(
        items=remaining_pages,
        request_builder=prepare_stage1_request,
        result_handler=handler,
        storage=storage,
        model=model,
        total_pages=total_pages,
    )

    return batch_stats
