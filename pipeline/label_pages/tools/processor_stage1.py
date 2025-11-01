"""Stage 1 processor: Page-level structural analysis with 3-image context."""

from concurrent.futures import ThreadPoolExecutor
from typing import List

from infra.llm.batch_client import LLMBatchProcessor, LLMResult
from infra.llm.utils import llm_result_to_metrics
from infra.storage.book_storage import BookStorage
from infra.storage.checkpoint import CheckpointManager
from infra.pipeline.logger import PipelineLogger


def process_stage1(
    storage: BookStorage,
    checkpoint: CheckpointManager,
    logger: PipelineLogger,
    stage_storage,
    model: str,
    max_workers: int,
    max_retries: int,
    remaining_pages: List[int],
    total_pages: int,
):
    """
    Run Stage 1: Structural analysis with 3-image context.

    Args:
        storage: Book storage
        checkpoint: Checkpoint manager
        logger: Pipeline logger
        stage_storage: Label pages stage storage
        model: Vision model to use
        max_workers: Max parallel workers
        max_retries: Max retry attempts
        remaining_pages: Pages that need Stage 1 processing
        total_pages: Total pages in book
    """
    if not remaining_pages:
        logger.info("No pages need Stage 1 processing")
        return

    logger.info(f"Stage 1: Processing {len(remaining_pages)} pages with 3-image context")
    logger.info(f"Model: {model}, Workers: {max_workers}")

    # Prepare Stage 1 requests in parallel
    from ..vision.caller_stage1 import prepare_stage1_request

    logger.info(f"Loading {len(remaining_pages)} page contexts...")
    requests = []

    def prepare_request(page_num):
        try:
            request = prepare_stage1_request(
                page_num=page_num,
                storage=storage,
                model=model,
                total_pages=total_pages,
            )
            return request
        except Exception as e:
            logger.warning(f"Failed to prepare Stage 1 request for page {page_num}", error=str(e))
            return None

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(prepare_request, page_num): page_num for page_num in remaining_pages}
        for future in futures:
            request = future.result()
            if request:
                requests.append(request)

    if not requests:
        logger.error("No valid Stage 1 requests prepared")
        return

    logger.info(f"Prepared {len(requests)} Stage 1 requests")

    # Process batch with LLMBatchProcessor
    stage_storage_dir = storage.stage(stage_storage.stage_name)
    log_dir = stage_storage_dir.output_dir / "logs" / "stage1"
    log_dir.mkdir(parents=True, exist_ok=True)

    processor = LLMBatchProcessor(
        checkpoint=checkpoint,
        logger=logger,
        model=model,
        log_dir=log_dir,
        max_retries=max_retries,
    )

    # Result handler: Save Stage 1 results
    def on_result(result: LLMResult):
        if result.success:
            page_num = result.metadata['page_num']
            stage1_data = result.parsed_json

            # Save Stage 1 intermediate result
            stage_storage.save_stage1_result(
                storage=storage,
                page_num=page_num,
                stage1_data=stage1_data,
                cost_usd=result.cost_usd or 0.0,
            )

            # Track cost in checkpoint
            checkpoint.mark_completed(
                page_num=page_num,
                cost_usd=result.cost_usd or 0.0,
                metrics={'stage': 'stage1'},
            )

            logger.info(f"✓ Stage 1 complete: page {page_num}")
        else:
            page_num = result.metadata.get('page_num', 'unknown')
            logger.error(f"✗ Stage 1 failed: page {page_num}", error=result.error)

    processor.process_batch(
        requests=requests,
        on_result=on_result,
    )

    logger.info(f"Stage 1 complete: {len(requests)} pages processed")
