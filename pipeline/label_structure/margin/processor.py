"""
Margin observation processor - Pass 1 of label-structure.

Simple batch processor for margin element extraction.
"""

from typing import Dict, Any, List

from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.llm.batch import LLMBatchProcessor, LLMBatchConfig

from .request_builder import prepare_margin_request
from .result_handler import create_margin_handler


def process_margin_pass(
    storage: BookStorage,
    logger: PipelineLogger,
    stage_name: str,
    remaining_pages: List[int],
    model: str,
    max_workers: int,
    max_retries: int,
    tracker=None
) -> Dict[str, Any]:
    """Process margin observation pass for remaining pages."""

    logger.info(f"=== Pass 1: Margin Elements ===")
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
            batch_name=f"{stage_name}-margin"
        ),
        tracker=tracker
    )
    handler = create_margin_handler(storage, logger, stage_name)

    # Process batch
    batch_stats = processor.process(
        items=remaining_pages,
        request_builder=prepare_margin_request,
        result_handler=handler,
        storage=storage,
        model=model,
    )

    return batch_stats
