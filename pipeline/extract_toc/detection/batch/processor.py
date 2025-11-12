from typing import Dict

from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.pipeline.status.batch_based import BatchBasedStatusTracker
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
    total_toc_pages = toc_range.end_page - toc_range.start_page + 1
    logger.info(f"Extracting ToC entries from {total_toc_pages} pages (parallel)")

    page_nums = list(range(toc_range.start_page, toc_range.end_page + 1))

    page_results = []

    # Setup tracker, handler, and config
    tracker = BatchBasedStatusTracker(storage, logger, 'extract-toc', "page_{:04d}.json")
    handler = create_toc_handler(storage, logger, page_results)

    config = LLMBatchConfig(
        tracker=tracker,
        model=model,
        batch_name="ToC entry extraction",
        request_builder=prepare_toc_request,
        result_handler=handler,
        max_workers=4,
        max_retries=3,
    )

    processor = LLMBatchProcessor(config)
    processor.process(
        items=page_nums,
        storage=storage,
        model=model,
        toc_range=toc_range,
        structure_notes_from_finder=structure_notes_from_finder,
        global_structure_from_finder=global_structure_from_finder,
        logger=logger
    )

    page_results.sort(key=lambda p: p["page_num"])

    return {
        "pages": page_results,
        "toc_range": toc_range.model_dump(),
    }
