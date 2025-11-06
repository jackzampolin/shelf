#!/usr/bin/env python3
import time
from typing import List, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from rich.console import Console

from .client import LLMBatchClient
from ..models import LLMRequest, LLMResult
from ..display_format import format_batch_summary
from .schemas import BatchStats, LLMBatchConfig
from infra.pipeline.logger import PipelineLogger
from infra.pipeline.rich_progress import RichProgressBarHierarchical
from infra.storage.book_storage import BookStorage
from infra.config import Config


class LLMBatchProcessor:
    def __init__(
        self,
        storage: BookStorage,
        stage_name: str,
        logger: PipelineLogger,
        config: LLMBatchConfig,
    ):
        self.logger = logger
        self.model = config.model
        self.max_workers = config.max_workers or Config.max_workers
        self.max_retries = config.max_retries
        self.retry_jitter = config.retry_jitter
        self.batch_name = config.batch_name

        self.metrics_manager = storage.stage(stage_name).metrics_manager

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
    ) -> BatchStats:
        if not items:
            self.logger.info(f"{self.batch_name}: No items to process")
            return BatchStats(
                total_requests=0, completed=0, failed=0, in_progress=0, queued=0,
                avg_time_per_request=0.0, min_time=0.0, max_time=0.0,
                total_cost_usd=0.0, avg_cost_per_request=0.0,
                total_prompt_tokens=0, total_tokens=0, total_reasoning_tokens=0,
                avg_tokens_per_request=0.0, requests_per_second=0.0,
                rate_limit_utilization=0.0, rate_limit_tokens_available=0
            )

        self.logger.info(f"{self.batch_name}: Processing {len(items)} items...")
        start_time = time.time()

        requests = self._prepare_requests(items, request_builder, **request_builder_kwargs)

        if not requests:
            self.logger.error(f"{self.batch_name}: No valid requests prepared")
            return BatchStats(
                total_requests=0, completed=0, failed=0, in_progress=0, queued=0,
                avg_time_per_request=0.0, min_time=0.0, max_time=0.0,
                total_cost_usd=0.0, avg_cost_per_request=0.0,
                total_prompt_tokens=0, total_tokens=0, total_reasoning_tokens=0,
                avg_tokens_per_request=0.0, requests_per_second=0.0,
                rate_limit_utilization=0.0, rate_limit_tokens_available=0
            )

        return self._execute_batch(requests, result_handler, start_time, len(items))

    def _prepare_requests(
        self,
        items: List,
        request_builder: Callable,
        **kwargs
    ) -> List[LLMRequest]:
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

        def prepare_single(item):
            try:
                return request_builder(item=item, **kwargs)
            except Exception as e:
                self.logger.warning(f"Failed to prepare item {item}", error=str(e))
                return None

        prepared = 0
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(prepare_single, item): item for item in items}
            for future in as_completed(futures):
                request = future.result()
                if request:
                    requests.append(request)

                prepared += 1
                prep_progress.update(prepared, suffix=f"{prepared}/{len(items)} prepared")

        prep_elapsed = time.time() - prep_start
        prep_progress.finish(f"   ✓ Prepared {len(requests)} requests in {prep_elapsed:.1f}s")
        self.logger.info(f"{self.batch_name}: Prepared {len(requests)}/{len(items)} requests")

        return requests

    def _execute_batch(
        self,
        requests: List[LLMRequest],
        result_handler: Callable,
        start_time: float,
        total_items: int
    ) -> BatchStats:
        progress = RichProgressBarHierarchical(
            total=len(requests),
            prefix="   ",
            width=40,
            unit="items",
        )
        progress.update(0, suffix="starting...")

        on_event = progress.create_llm_event_handler(
            batch_client=self.batch_client,
            start_time=start_time,
            model=self.model,
            total_requests=len(requests),
            metrics_manager=self.metrics_manager,
        )

        try:
            self.batch_client.process_batch(
                requests,
                on_event=on_event,
                on_result=result_handler,
            )
        finally:
            elapsed = time.time() - start_time
            batch_stats = self.batch_client.get_batch_stats(total_requests=len(requests))

            self._display_summary(progress, batch_stats, elapsed, total_items)

            self.logger.info(
                f"{self.batch_name} complete: {batch_stats.completed} completed, "
                f"{batch_stats.failed} failed, "
                f"${batch_stats.total_cost_usd:.4f}"
            )

        return batch_stats

    def _display_summary(
        self,
        progress: RichProgressBarHierarchical,
        batch_stats,
        elapsed: float,
        total_items: int
    ):
        if self.metrics_manager:
            cumulative = self.metrics_manager.get_cumulative_metrics()
            display_completed = cumulative.get('total_requests', batch_stats.completed)
            display_total = cumulative.get('total_requests', batch_stats.completed)
            display_prompt_tokens = cumulative.get('total_prompt_tokens', batch_stats.total_prompt_tokens)
            display_completion_tokens = cumulative.get('total_completion_tokens', batch_stats.total_tokens)
            display_reasoning_tokens = cumulative.get('total_reasoning_tokens', batch_stats.total_reasoning_tokens)
            display_cost = cumulative.get('total_cost_usd', batch_stats.total_cost_usd)

            runtime_metrics = self.metrics_manager.get("stage_runtime")
            display_time = runtime_metrics.get("time_seconds", elapsed) if runtime_metrics else elapsed
        else:
            display_completed = batch_stats.completed
            display_total = total_items
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

        console = Console()
        with console.capture() as capture:
            console.print(summary_text)
        progress.finish(capture.get().rstrip())


__all__ = ['LLMBatchProcessor', 'LLMBatchConfig']
