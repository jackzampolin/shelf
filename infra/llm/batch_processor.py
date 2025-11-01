#!/usr/bin/env python3
"""
Simplified LLM batch processor - pure orchestration layer.

Provides:
- Parallel LLM execution with retries
- Progress bar with token/cost tracking
- Event callbacks for result handling
- Aggregate batch statistics

Callers handle:
- Result parsing
- Persistence (files, checkpoint, etc.)
- Schema validation
- Error recovery

This separation makes the processor reusable across any LLM batch workflow,
not just page-based pipeline stages.
"""

import time
from pathlib import Path
from typing import List, Dict, Any, Callable, Optional

from infra.llm.batch_client import LLMBatchClient, LLMRequest, LLMResult
from infra.storage.checkpoint import CheckpointManager
from infra.pipeline.logger import PipelineLogger
from infra.pipeline.rich_progress import RichProgressBarHierarchical
from infra.config import Config


class LLMBatchProcessor:
    """
    Simplified LLM batch processor - pure orchestration.

    Responsibilities:
    - Parallel LLM execution with retries
    - Progress tracking with token/cost display
    - Event callbacks for lifecycle hooks

    Caller responsibilities:
    - Parse and validate results
    - Persist outputs (files, checkpoint, database, etc.)
    - Handle errors and retries
    - Update application state

    Usage:
        processor = LLMBatchProcessor(
            checkpoint=checkpoint,
            logger=logger,
            model="grok-4-fast",
            log_dir=Path("logs/"),
        )

        def handle_result(result: LLMResult):
            if result.success:
                data = parse_my_data(result.parsed_json)
                save_to_disk(data)
                checkpoint.update_page_metrics(...)
            else:
                logger.error(f"Failed: {result.error_message}")

        stats = processor.process_batch(
            requests=requests,
            on_result=handle_result,
        )

        # stats contains: completed, failed, total_cost_usd, total_tokens, etc.
    """

    def __init__(
        self,
        checkpoint: CheckpointManager,
        logger: PipelineLogger,
        model: str,
        log_dir: Path,
        max_workers: Optional[int] = None,
        max_retries: int = 3,
        retry_jitter: tuple = (1.0, 3.0),
        verbose: bool = True,
    ):
        """
        Args:
            checkpoint: CheckpointManager for progress bar metrics display
            logger: PipelineLogger instance
            model: OpenRouter model name
            log_dir: Directory for LLM request/response logs
            max_workers: Thread pool size (default: Config.max_workers)
            max_retries: Max retry attempts per request
            retry_jitter: Retry delay range in seconds
            verbose: Enable verbose logging
        """
        self.checkpoint = checkpoint
        self.logger = logger
        self.model = model
        self.log_dir = log_dir

        # Create log directory
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Create batch client
        self.batch_client = LLMBatchClient(
            max_workers=max_workers or Config.max_workers,
            max_retries=max_retries,
            retry_jitter=retry_jitter,
            verbose=verbose,
            log_dir=self.log_dir,
        )

    def process_batch(
        self,
        requests: List[LLMRequest],
        on_result: Callable[[LLMResult], None],
    ) -> Dict[str, Any]:
        """
        Process a batch of LLM requests with progress tracking.

        Args:
            requests: List of LLM requests to process
            on_result: Callback for each completed request
                      Signature: (result: LLMResult) -> None
                      Caller handles parsing, validation, persistence

        Returns:
            Stats dict with:
            - completed: Number of successful requests
            - failed: Number of failed requests
            - total_cost_usd: Total cost in USD
            - total_tokens: Total tokens processed
            - total_reasoning_tokens: Total reasoning tokens
            - elapsed_seconds: Total elapsed time
            - batch_stats: Full BatchStats object
        """
        if not requests:
            return {
                "completed": 0,
                "failed": 0,
                "total_cost_usd": 0.0,
                "total_tokens": 0,
                "total_reasoning_tokens": 0,
                "elapsed_seconds": 0.0,
                "batch_stats": None,
            }

        self.logger.info(f"Processing {len(requests)} LLM requests...")
        start_time = time.time()

        # Create hierarchical progress bar
        progress = RichProgressBarHierarchical(
            total=len(requests),
            prefix="   ",
            width=40,
            unit="pages",
        )
        progress.update(0, suffix="starting...")

        # Create event handler (wires up progress bar)
        on_event = progress.create_llm_event_handler(
            batch_client=self.batch_client,
            start_time=start_time,
            model=self.model,
            total_requests=len(requests),
            checkpoint=self.checkpoint,
        )

        # Execute batch (caller's on_result handles everything)
        try:
            self.batch_client.process_batch(
                requests,
                on_event=on_event,
                on_result=on_result,  # Caller handles parsing, validation, persistence
            )
        finally:
            # Get final stats
            elapsed = time.time() - start_time
            batch_stats = self.batch_client.get_batch_stats(total_requests=len(requests))

            progress.finish(
                f"   ✓ {batch_stats.completed}/{len(requests)} requests in {elapsed:.1f}s"
            )

            self.logger.info(
                f"Batch complete: {batch_stats.completed} completed, "
                f"{batch_stats.failed} failed, "
                f"${batch_stats.total_cost_usd:.4f}, "
                f"{batch_stats.total_tokens} tokens"
            )

        return {
            "completed": batch_stats.completed,
            "failed": batch_stats.failed,
            "total_cost_usd": batch_stats.total_cost_usd,
            "total_tokens": batch_stats.total_tokens,
            "total_reasoning_tokens": batch_stats.total_reasoning_tokens,
            "elapsed_seconds": elapsed,
            "batch_stats": batch_stats,
        }


def batch_process_with_preparation(
    stage_name: str,
    pages: List[int],
    request_builder: Callable,
    result_handler: Callable[[LLMResult], None],
    processor: 'LLMBatchProcessor',
    logger: 'PipelineLogger',
    max_workers: int,
    **request_builder_kwargs
) -> Dict[str, Any]:
    """
    Generic helper: Prepare requests in parallel, then process batch.

    Eliminates duplication across stages (paragraph_correct, label_pages, etc.)

    Args:
        stage_name: Name for logging (e.g., "Stage 1", "Correction")
        pages: List of page numbers to process
        request_builder: Function that builds LLMRequest for a page
            Signature: (page_num, **kwargs) -> LLMRequest or (LLMRequest, extra_data)
        result_handler: Callback for each completed request
            Signature: (result: LLMResult) -> None
        processor: LLMBatchProcessor instance
        logger: Pipeline logger
        max_workers: Max parallel workers for request preparation
        **request_builder_kwargs: Extra kwargs passed to request_builder

    Returns:
        Stats dict from processor.process_batch()
    """
    from concurrent.futures import ThreadPoolExecutor

    if not pages:
        logger.info(f"{stage_name}: No pages to process")
        return {
            "completed": 0,
            "failed": 0,
            "total_cost_usd": 0.0,
            "total_tokens": 0,
        }

    logger.info(f"{stage_name}: Preparing {len(pages)} requests...")

    requests = []
    extra_data = {}

    def prepare_request(page_num):
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

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(prepare_request, page_num): page_num for page_num in pages}
        for future in futures:
            request, extra = future.result()
            if request:
                requests.append(request)
                if extra:
                    page_num = request.metadata.get('page_num')
                    if page_num:
                        extra_data[page_num] = extra

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
            page_num = result.metadata.get('page_num')
            if page_num and page_num in extra_data:
                result.metadata['extra_data'] = extra_data[page_num]
            original_handler(result)

        result_handler = wrapped_handler

    # Process batch
    return processor.process_batch(
        requests=requests,
        on_result=result_handler,
    )
