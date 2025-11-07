from typing import Dict

from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.llm.batch import LLMBatchProcessor, LLMBatchConfig

from ...schemas import PageRange
from .request_builder import prepare_toc_request
from .result_handler import create_toc_handler


def process_toc_pages(
    storage: BookStorage,
    logger: PipelineLogger,
    toc_range: PageRange,
    structure_notes_from_finder: Dict[int, str],
    global_structure_from_finder: dict,
    model: str
) -> Dict:
    """Process ToC pages using LLMBatchProcessor.

    Args:
        storage: BookStorage
        logger: Pipeline logger
        toc_range: Range of ToC pages
        structure_notes_from_finder: Per-page structure observations
        global_structure_from_finder: Global structure summary
        model: Model to use

    Returns:
        Dict with pages list and toc_range
    """
    total_toc_pages = toc_range.end_page - toc_range.start_page + 1
    logger.info(f"Extracting ToC entries from {total_toc_pages} pages (parallel)")

    # Prepare items (page numbers)
    page_nums = list(range(toc_range.start_page, toc_range.end_page + 1))

    # Setup result collection
    page_results = []
    handler = create_toc_handler(logger, page_results)

    # Process batch
    processor = LLMBatchProcessor(
        storage=storage,
        stage_name='extract-toc',
        logger=logger,
        config=LLMBatchConfig(
            model=model,
            max_workers=4,
            max_retries=3,
            batch_name="ToC entry extraction"
        )
    )

    processor.process(
        items=page_nums,
        request_builder=prepare_toc_request,
        result_handler=handler,
        storage=storage,
        model=model,
        toc_range=toc_range,
        structure_notes_from_finder=structure_notes_from_finder,
        global_structure_from_finder=global_structure_from_finder,
        logger=logger
    )

    # Sort page_results by page_num
    page_results.sort(key=lambda p: p["page_num"])

    return {
        "pages": page_results,
        "toc_range": toc_range.model_dump(),
    }
