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
- Persistence (files, etc.)
- Schema validation
- Error recovery

This separation makes the processor reusable across any LLM batch workflow,
not just page-based pipeline stages.
"""

import time
from pathlib import Path
from typing import List, Dict, Any, Callable, Optional
from dataclasses import dataclass

from infra.llm.batch_client import LLMBatchClient, LLMRequest, LLMResult
from infra.llm.display_format import format_batch_summary
from infra.pipeline.logger import PipelineLogger
from infra.pipeline.rich_progress import RichProgressBarHierarchical
from infra.config import Config


@dataclass
class LLMBatchConfig:
    """
    Configuration for LLM batch processing.

    Encapsulates all settings needed to configure an LLMBatchProcessor instance.
    This makes it easy to see what parameters are required and provides a clean
    interface for stage implementations.
    """
    model: str
    max_workers: Optional[int] = None  # Default: Config.max_workers
    max_retries: int = 3
    retry_jitter: tuple = (1.0, 3.0)
    verbose: bool = True
    batch_name: str = "LLM"  # Display name for progress/summary


class LLMBatchProcessor:
    """
    Simplified LLM batch processor - pure orchestration.

    Responsibilities:
    - Parallel LLM execution with retries
    - Progress tracking with token/cost display
    - Event callbacks for lifecycle hooks

    Caller responsibilities:
    - Parse and validate results
    - Persist outputs (files, database, etc.)
    - Handle errors and retries
    - Update application state

    Usage:
        config = LLMBatchConfig(model="grok-4-fast")
        processor = LLMBatchProcessor(
            logger=logger,
            log_dir=Path("logs/"),
            config=config,
        )

        def handle_result(result: LLMResult):
            if result.success:
                data = parse_my_data(result.parsed_json)
                save_to_disk(data)
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
        logger: PipelineLogger,
        log_dir: Path,
        config: Optional[LLMBatchConfig] = None,
        metrics_manager=None,  # Optional MetricsManager for progress bar display
        checkpoint=None,  # Deprecated, ignored
        # Legacy parameters (for backward compatibility)
        model: Optional[str] = None,
        max_workers: Optional[int] = None,
        max_retries: Optional[int] = None,
        retry_jitter: Optional[tuple] = None,
        verbose: Optional[bool] = None,
    ):
        """
        Initialize LLMBatchProcessor.

        Supports two initialization patterns:

        1. **New (recommended):** Use LLMBatchConfig
           ```python
           config = LLMBatchConfig(model="grok-4-fast", max_workers=10)
           processor = LLMBatchProcessor(logger, log_dir, config=config)
           ```

        2. **Legacy:** Pass parameters directly (for backward compatibility)
           ```python
           processor = LLMBatchProcessor(logger, log_dir, model="grok-4-fast")
           ```

        Args:
            logger: PipelineLogger instance
            log_dir: Directory for LLM request/response logs
            config: LLMBatchConfig instance (recommended)
            metrics_manager: Optional MetricsManager for real-time progress display
            checkpoint: Deprecated, no longer used
            model: OpenRouter model name (legacy, use config instead)
            max_workers: Thread pool size (legacy, use config instead)
            max_retries: Max retry attempts (legacy, use config instead)
            retry_jitter: Retry delay range (legacy, use config instead)
            verbose: Enable verbose logging (legacy, use config instead)
        """
        self.logger = logger
        self.log_dir = log_dir
        self.metrics_manager = metrics_manager

        # Handle both config-based and legacy parameter-based initialization
        if config is not None:
            # New pattern: Use config object
            self.model = config.model
            self.max_workers = config.max_workers or Config.max_workers
            self.max_retries = config.max_retries
            self.retry_jitter = config.retry_jitter
            self.verbose = config.verbose
            self.batch_name = config.batch_name
        else:
            # Legacy pattern: Use individual parameters
            if model is None:
                raise ValueError("Either 'config' or 'model' must be provided")
            self.model = model
            self.max_workers = max_workers or Config.max_workers
            self.max_retries = max_retries if max_retries is not None else 3
            self.retry_jitter = retry_jitter if retry_jitter is not None else (1.0, 3.0)
            self.verbose = verbose if verbose is not None else True
            self.batch_name = "LLM"  # Default for legacy usage

        # Create log directory
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Create batch client
        self.batch_client = LLMBatchClient(
            max_workers=self.max_workers,
            max_retries=self.max_retries,
            retry_jitter=self.retry_jitter,
            verbose=self.verbose,
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
            metrics_manager=self.metrics_manager,
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

            # Use cumulative metrics from MetricsManager if available (for stages with resume)
            # This ensures the display shows total cost/tokens across ALL batches,
            # not just the current batch (which may be a small resume).
            # For time: Use wall-clock stage_runtime if available, else fall back to current batch elapsed.
            # Otherwise fall back to batch_stats (for standalone LLM calls).
            if self.metrics_manager:
                cumulative = self.metrics_manager.get_cumulative_metrics()
                display_completed = cumulative.get('total_requests', batch_stats.completed)
                display_total = cumulative.get('total_requests', batch_stats.completed)  # After batch complete, completed == total
                display_prompt_tokens = cumulative.get('total_prompt_tokens', batch_stats.total_prompt_tokens)
                display_completion_tokens = cumulative.get('total_completion_tokens', batch_stats.total_tokens)
                display_reasoning_tokens = cumulative.get('total_reasoning_tokens', batch_stats.total_reasoning_tokens)
                display_cost = cumulative.get('total_cost_usd', batch_stats.total_cost_usd)

                # Use wall-clock stage_runtime (not sum of individual request times)
                runtime_metrics = self.metrics_manager.get("stage_runtime")
                display_time = runtime_metrics.get("time_seconds", elapsed) if runtime_metrics else elapsed
            else:
                display_completed = batch_stats.completed
                display_total = len(requests)
                display_prompt_tokens = batch_stats.total_prompt_tokens
                display_completion_tokens = batch_stats.total_tokens
                display_reasoning_tokens = batch_stats.total_reasoning_tokens
                display_cost = batch_stats.total_cost_usd
                display_time = elapsed

            summary_text = format_batch_summary(
                batch_name=self.batch_name,
                completed=display_completed,
                total=display_total,
                time_seconds=display_time,
                prompt_tokens=display_prompt_tokens,
                completion_tokens=display_completion_tokens,
                reasoning_tokens=display_reasoning_tokens,
                cost_usd=display_cost,
                unit="requests"
            )
            # RichProgressBarHierarchical.finish() needs a string, so convert
            from rich.console import Console
            console = Console()
            with console.capture() as capture:
                console.print(summary_text)
            progress.finish(capture.get().rstrip())

            self.logger.info(
                f"Batch complete: {display_completed} completed, "
                f"{batch_stats.failed} failed, "
                f"${display_cost:.4f}, "
                f"{display_completion_tokens} tokens"
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
        processor: LLMBatchProcessor instance (max_workers taken from processor.max_workers)
        logger: Pipeline logger
        **request_builder_kwargs: Extra kwargs passed to request_builder

    Returns:
        Stats dict from processor.process_batch()
    """
    max_workers = processor.max_workers
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from infra.pipeline.rich_progress import RichProgressBarHierarchical
    import time

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
