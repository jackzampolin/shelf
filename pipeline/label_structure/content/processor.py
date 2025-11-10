"""
Content flow processor - Pass 3 of label-structure.

Text-only batch processor for content flow analysis.
"""

from typing import Dict, Any, List

from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.llm.batch import LLMBatchProcessor, LLMBatchConfig

from .request_builder import prepare_content_request
from .result_handler import create_content_handler


def process_content_pass(
    storage: BookStorage,
    logger: PipelineLogger,
    stage_name: str,
    remaining_pages: List[int],
    model: str,
    max_workers: int,
    max_retries: int
) -> Dict[str, Any]:
    """Process content flow pass for remaining pages."""

    logger.info(f"=== Pass 3: Content Flow (text-only) ===")
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
            batch_name=f"{stage_name}-content"
        ),
    )
    handler = create_content_handler(storage, logger, stage_name)

    # Process batch
    batch_stats = processor.process(
        items=remaining_pages,
        request_builder=prepare_content_request,
        result_handler=handler,
        storage=storage,
        model=model,
        stage_name=stage_name,
    )

    return batch_stats
