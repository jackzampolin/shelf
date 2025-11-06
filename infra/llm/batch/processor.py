#!/usr/bin/env python3
"""
Clean LLM batch processor with integrated request preparation.

Interface:
    processor = LLMBatchProcessor(
        storage=storage,           # Single source of truth
        stage_name="label-pages",  # For log directory
        logger=logger,
        config=LLMBatchConfig(
            model="grok-4-fast",
            max_workers=10,
            max_retries=3,
            batch_name="Stage 1"   # For display (useful with multi-processor stages)
        )
    )

    stats = processor.process(
        items=remaining_pages,           # Generic: pages, chunks, docs
        request_builder=build_request,   # (item, **kwargs) -> LLMRequest
        result_handler=handle_result,    # (result: LLMResult) -> None
        # kwargs passed to request_builder:
        model=self.model,
        total_items=total_pages
    )

Request builder gets storage from closure (doesn't need to be passed).
"""

import time
from pathlib import Path
from typing import List, Dict, Any, Callable, Optional
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from rich.console import Console

from .client import LLMBatchClient
from ..models import LLMRequest, LLMResult
from ..display_format import format_batch_summary
from infra.pipeline.logger import PipelineLogger
from infra.pipeline.rich_progress import RichProgressBarHierarchical
from infra.storage.book_storage import BookStorage
from infra.config import Config


@dataclass
class LLMBatchConfig:
    """
    Configuration for LLM batch processing.

    Attributes:
        model: OpenRouter model name (e.g., "grok-4-fast")
        max_workers: Thread pool size (default: Config.max_workers)
        max_retries: Max retry attempts per request
        retry_jitter: (min, max) seconds between retries
        batch_name: Display name for progress (useful for multi-processor stages)
    """
    model: str
    max_workers: Optional[int] = None
    max_retries: int = 3
    retry_jitter: tuple = (1.0, 3.0)
    batch_name: str = "LLM Batch"


class LLMBatchProcessor:
    """
    Clean LLM batch processor with integrated request preparation.

    Responsibilities:
    - Parallel request preparation (load data for all items concurrently)
    - Parallel LLM execution with retries and rate limiting
    - Progress tracking with cost/token/throughput display
    - Metrics recording to storage

    Caller responsibilities:
    - Build LLMRequest for each item (request_builder)
    - Handle results: parse, validate, persist (result_handler)

    Thread Safety:
    All state managed by LLMBatchClient (thread-safe).
    """

    def __init__(
        self,
        storage: BookStorage,
        stage_name: str,
        logger: PipelineLogger,
        config: LLMBatchConfig,
    ):
        """
        Initialize batch processor.

        Args:
            storage: BookStorage (single source of truth for metrics + logs)
            stage_name: Stage name for log directory (e.g., "label-pages")
            logger: Pipeline logger
            config: Batch configuration
        """
        self.storage = storage
        self.stage_name = stage_name
        self.logger = logger
        self.config = config

        # Extract config
        self.model = config.model
        self.max_workers = config.max_workers or Config.max_workers
        self.max_retries = config.max_retries
        self.retry_jitter = config.retry_jitter
        self.batch_name = config.batch_name

        # Derive from storage (single source of truth)
        stage_storage = storage.stage(stage_name)
        self.metrics_manager = stage_storage.metrics_manager

        # Create batch client
        self.batch_client = LLMBatchClient(
            max_workers=self.max_workers,
            max_retries=self.max_retries,
            retry_jitter=self.retry_jitter,
        )

    def process(
        self,
        items: List,
        request_builder: Callable,
        result_handler: Callable[[LLMResult], None],
        **request_builder_kwargs
    ) -> Dict[str, Any]:
        """
        Process batch: prepare requests in parallel, execute with progress.

        Two phases:
        1. Preparation: Call request_builder for each item in parallel
        2. Execution: Send prepared requests to LLM with retries

        Args:
            items: List of items to process (page numbers, chunk IDs, etc.)
            request_builder: Build LLMRequest for one item
                Signature: (item, **kwargs) -> LLMRequest or (LLMRequest, extra_data)
                Gets storage from closure (no need to pass)
            result_handler: Handle each completed request
                Signature: (result: LLMResult) -> None
                Caller handles: parsing, validation, persistence
            **request_builder_kwargs: Passed to request_builder
                Common: model, total_items, etc.

        Returns:
            Stats dict:
            - completed: Successful requests
            - failed: Failed requests (after all retries)
            - total_cost_usd: Total cost
            - total_tokens: Total completion tokens
            - total_reasoning_tokens: Total reasoning tokens
            - elapsed_seconds: Wall-clock time
            - batch_stats: Full BatchStats object
        """
        if not items:
            self.logger.info(f"{self.batch_name}: No items to process")
            return self._empty_stats()

        self.logger.info(f"{self.batch_name}: Processing {len(items)} items...")
        start_time = time.time()

        # Phase 1: Prepare requests in parallel
        requests, extra_data = self._prepare_requests(
            items, request_builder, **request_builder_kwargs
        )

        if not requests:
            self.logger.error(f"{self.batch_name}: No valid requests prepared")
            return self._empty_stats()

        # Wrap result_handler to inject extra_data if present
        wrapped_handler = self._wrap_handler(result_handler, extra_data)

        # Phase 2: Execute batch with progress tracking
        return self._execute_batch(requests, wrapped_handler, start_time, len(items))

    def _prepare_requests(
        self,
        items: List,
        request_builder: Callable,
        **kwargs
    ) -> tuple:
        """
        Prepare LLMRequests in parallel.

        Returns:
            Tuple of (requests, extra_data)
        """
        self.logger.info(f"{self.batch_name}: Preparing {len(items)} requests...")

        prep_start = time.time()
        prep_progress = RichProgressBarHierarchical(
            total=len(items),
            prefix="   ",
            width=40,
            unit="requests"
        )
        prep_progress.update(0, suffix="loading data...")

        requests = []
        extra_data = {}

        def prepare_single(item):
            """Prepare one request (called in parallel)."""
            try:
                result = request_builder(item=item, **kwargs)
                # Handle both single return and tuple return
                if isinstance(result, tuple):
                    return result
                return (result, None)
            except Exception as e:
                self.logger.warning(f"Failed to prepare item {item}", error=str(e))
                return (None, None)

        # Parallel preparation
        prepared = 0
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(prepare_single, item): item for item in items}
            for future in as_completed(futures):
                request, extra = future.result()
                if request:
                    requests.append(request)
                    if extra:
                        # Store by item identifier
                        item_id = request.metadata.get('page_num') or request.metadata.get('item')
                        if item_id:
                            extra_data[item_id] = extra

                prepared += 1
                prep_progress.update(prepared, suffix=f"{prepared}/{len(items)} prepared")

        prep_elapsed = time.time() - prep_start
        prep_progress.finish(f"   ✓ Prepared {len(requests)} requests in {prep_elapsed:.1f}s")
        self.logger.info(f"{self.batch_name}: Prepared {len(requests)}/{len(items)} requests")

        return requests, extra_data

    def _wrap_handler(
        self,
        result_handler: Callable,
        extra_data: Dict
    ) -> Callable:
        """Wrap result_handler to inject extra_data if present."""
        if not extra_data:
            return result_handler

        def wrapped(result: LLMResult):
            item = result.request.metadata.get('page_num') or result.request.metadata.get('item')
            if item and item in extra_data:
                result.request.metadata['extra_data'] = extra_data[item]
            result_handler(result)

        return wrapped

    def _execute_batch(
        self,
        requests: List[LLMRequest],
        result_handler: Callable,
        start_time: float,
        total_items: int
    ) -> Dict[str, Any]:
        """Execute batch with progress tracking."""
        # Create progress bar
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

        # Execute
        try:
            self.batch_client.process_batch(
                requests,
                on_event=on_event,
                on_result=result_handler,
            )
        finally:
            # Get final stats
            elapsed = time.time() - start_time
            batch_stats = self.batch_client.get_batch_stats(total_requests=len(requests))

            # Display summary (use cumulative metrics if available)
            self._display_summary(progress, batch_stats, elapsed, total_items)

            self.logger.info(
                f"{self.batch_name} complete: {batch_stats.completed} completed, "
                f"{batch_stats.failed} failed, "
                f"${batch_stats.total_cost_usd:.4f}"
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

    def _display_summary(
        self,
        progress: RichProgressBarHierarchical,
        batch_stats,
        elapsed: float,
        total_items: int
    ):
        """Display final summary using cumulative metrics if available."""
        # Use cumulative metrics from MetricsManager if available (for resume)
        if self.metrics_manager:
            cumulative = self.metrics_manager.get_cumulative_metrics()
            display_completed = cumulative.get('total_requests', batch_stats.completed)
            display_total = cumulative.get('total_requests', batch_stats.completed)
            display_prompt_tokens = cumulative.get('total_prompt_tokens', batch_stats.total_prompt_tokens)
            display_completion_tokens = cumulative.get('total_completion_tokens', batch_stats.total_tokens)
            display_reasoning_tokens = cumulative.get('total_reasoning_tokens', batch_stats.total_reasoning_tokens)
            display_cost = cumulative.get('total_cost_usd', batch_stats.total_cost_usd)

            # Use wall-clock stage_runtime (not sum of request times)
            runtime_metrics = self.metrics_manager.get("stage_runtime")
            display_time = runtime_metrics.get("time_seconds", elapsed) if runtime_metrics else elapsed
        else:
            display_completed = batch_stats.completed
            display_total = len(total_items) if total_items else batch_stats.completed
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

        # Convert Rich text to string for progress bar
        console = Console()
        with console.capture() as capture:
            console.print(summary_text)
        progress.finish(capture.get().rstrip())

    def _empty_stats(self) -> Dict[str, Any]:
        """Return empty stats dict."""
        return {
            "completed": 0,
            "failed": 0,
            "total_cost_usd": 0.0,
            "total_tokens": 0,
            "total_reasoning_tokens": 0,
            "elapsed_seconds": 0.0,
            "batch_stats": None,
        }


__all__ = ['LLMBatchProcessor', 'LLMBatchConfig']
