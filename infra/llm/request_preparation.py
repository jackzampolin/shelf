#!/usr/bin/env python3
"""
Parallel request preparation for batch processing.

Eliminates duplication across pipeline stages by providing a generic helper
that prepares LLM requests in parallel before batch execution.

Used by stages like label-pages, extract-toc, etc. to load data (images, text)
and build LLMRequest objects concurrently before sending to the batch processor.
"""

import time
from typing import List, Dict, Any, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from infra.llm.models import LLMResult
from infra.pipeline.rich_progress import RichProgressBarHierarchical
from infra.pipeline.logger import PipelineLogger


def batch_process_with_preparation(
    stage_name: str,
    pages: List[int],
    request_builder: Callable,
    result_handler: Callable[[LLMResult], None],
    processor: 'LLMBatchProcessor',
    logger: PipelineLogger,
    **request_builder_kwargs
) -> Dict[str, Any]:
    """
    Generic helper: Prepare requests in parallel, then process batch.

    Eliminates duplication across stages (label-pages, extract-toc, etc.)

    Two-phase approach:
    1. **Preparation phase**: Build LLMRequest objects in parallel
       - Loads data (images, OCR text, etc.) for each page
       - Creates LLMRequest with messages, images, metadata
       - Progress bar shows "X/Y prepared"

    2. **Processing phase**: Send prepared requests to batch processor
       - Uses processor.process_batch() for LLM execution
       - Progress bar shows cost, tokens, throughput

    This pattern allows data loading (I/O bound) to happen in parallel
    before LLM processing (API bound).

    Args:
        stage_name: Name for logging (e.g., "Label-Pages", "Extract ToC")
        pages: List of page numbers to process
        request_builder: Function that builds LLMRequest for a page
            Signature: (page_num, **kwargs) -> LLMRequest or (LLMRequest, extra_data)
            Returns either LLMRequest alone, or tuple of (LLMRequest, extra_data)
        result_handler: Callback for each completed request
            Signature: (result: LLMResult) -> None
            Handles parsing, validation, persistence
        processor: LLMBatchProcessor instance (max_workers taken from processor.max_workers)
        logger: Pipeline logger
        **request_builder_kwargs: Extra kwargs passed to request_builder
            Common: storage, model, total_pages, etc.

    Returns:
        Stats dict from processor.process_batch():
        - completed: Number of successful requests
        - failed: Number of failed requests
        - total_cost_usd: Total cost in USD
        - total_tokens: Total tokens processed
        - elapsed_seconds: Total elapsed time

    Example:
        ```python
        def build_request(page_num, storage, model):
            # Load data for this page
            image = load_image(page_num)
            ocr_text = load_ocr(page_num)

            # Build LLM request
            return LLMRequest(
                id=f"page_{page_num:04d}",
                model=model,
                messages=[...],
                images=[image],
                metadata={'page_num': page_num}
            )

        def handle_result(result: LLMResult):
            if result.success:
                save_output(result.parsed_json)
            else:
                logger.error(f"Failed: {result.error_message}")

        stats = batch_process_with_preparation(
            stage_name="My Stage",
            pages=[1, 2, 3, 4, 5],
            request_builder=build_request,
            result_handler=handle_result,
            processor=processor,
            logger=logger,
            storage=storage,
            model="grok-4-fast"
        )
        ```
    """
    max_workers = processor.max_workers

    if not pages:
        logger.info(f"{stage_name}: No pages to process")
        return {
            "completed": 0,
            "failed": 0,
            "total_cost_usd": 0.0,
            "total_tokens": 0,
        }

    logger.info(f"{stage_name}: Preparing {len(pages)} requests...")

    # Create progress bar for request preparation phase
    prep_start = time.time()
    prep_progress = RichProgressBarHierarchical(
        total=len(pages),
        prefix="   ",
        width=40,
        unit="requests"
    )
    prep_progress.update(0, suffix="loading data...")

    requests = []
    extra_data = {}

    def prepare_request(page_num):
        """Prepare single request (called in parallel)."""
        try:
            result = request_builder(page_num=page_num, **request_builder_kwargs)
            # Handle both single return (LLMRequest) and tuple (LLMRequest, extra)
            if isinstance(result, tuple):
                return result
            else:
                return (result, None)
        except Exception as e:
            logger.warning(f"Failed to prepare request for page {page_num}", error=str(e))
            return (None, None)

    # Prepare requests in parallel
    prepared = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(prepare_request, page_num): page_num for page_num in pages}
        for future in as_completed(futures):
            request, extra = future.result()
            if request:
                requests.append(request)
                if extra:
                    page_num = request.metadata.get('page_num')
                    if page_num:
                        extra_data[page_num] = extra

            # Update progress
            prepared += 1
            prep_progress.update(prepared, suffix=f"{prepared}/{len(pages)} prepared")

    # Finish preparation progress bar
    prep_elapsed = time.time() - prep_start
    prep_progress.finish(f"   ✓ Prepared {len(requests)} requests in {prep_elapsed:.1f}s")

    if not requests:
        logger.error(f"{stage_name}: No valid requests prepared")
        return {
            "completed": 0,
            "failed": 0,
            "total_cost_usd": 0.0,
            "total_tokens": 0,
        }

    logger.info(f"{stage_name}: Prepared {len(requests)} requests")

    # If result_handler needs extra_data, inject it into metadata
    if extra_data:
        original_handler = result_handler

        def wrapped_handler(result: LLMResult):
            page_num = result.request.metadata.get('page_num')
            if page_num and page_num in extra_data:
                result.request.metadata['extra_data'] = extra_data[page_num]
            original_handler(result)

        result_handler = wrapped_handler

    # Process batch
    return processor.process_batch(
        requests=requests,
        on_result=result_handler,
    )
