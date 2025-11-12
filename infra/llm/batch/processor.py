#!/usr/bin/env python3
import time
import threading
from typing import List

from .client import LLMBatchClient
from .progress import create_progress_handler
from .progress.display import display_summary
from .schemas import BatchStats, LLMBatchConfig
from infra.pipeline.rich_progress import RichProgressBarHierarchical
from infra.config import Config


class LLMBatchProcessor:
    def __init__(self, config: LLMBatchConfig):
        self.config = config
        self.tracker = config.tracker
        self.logger = config.tracker.logger
        self.storage = config.tracker.storage
        self.stage_name = config.tracker.stage_name

        self.model = config.model
        self.max_workers = config.max_workers or Config.max_workers
        self.max_retries = config.max_retries
        self.retry_jitter = config.retry_jitter
        self.batch_name = config.batch_name
        self.request_builder = config.request_builder
        self.result_handler = config.result_handler

        self.metrics_manager = self.storage.stage(self.stage_name).metrics_manager

        pattern = self.tracker.item_pattern
        self.metric_prefix = pattern.replace('{:04d}', '').replace('.json', '')

        self.batch_client = LLMBatchClient(
            max_workers=self.max_workers,
            max_retries=self.max_retries,
            retry_jitter=self.retry_jitter,
            logger=self.logger,
        )

    def get_batch_stats(self, total_items: int) -> BatchStats:
        from .progress.rollups import aggregate_batch_stats

        return aggregate_batch_stats(
            metrics_manager=self.metrics_manager,
            active_requests=self.batch_client.worker_pool.get_active_requests(),
            total_requests=total_items,
            rate_limit_status=self.batch_client.rate_limiter.get_status(),
            batch_start_time=self.batch_client.batch_start_time or time.time()
        )

    def process(
        self,
        **request_builder_kwargs
    ) -> BatchStats:
        """
        Process all remaining items from tracker using batch LLM processing.

        The processor automatically:
        - Gets items from self.tracker.get_remaining_items()
        - Injects storage=self.storage and model=self.model to request_builder
        - Any additional kwargs are forwarded to request_builder

        Args:
            **request_builder_kwargs: Optional extra kwargs for request_builder
        """
        # Get items from tracker
        items = self.tracker.get_remaining_items()

        if not items:
            self.logger.info(f"{self.batch_name}: No items to process")
            return BatchStats()

        self.logger.info(f"{self.batch_name}: Processing {len(items)} items...")
        start_time = time.time()

        prep_start = time.time()
        prep_progress = RichProgressBarHierarchical(
            total=len(items),
            prefix="",
            width=40,
            unit="requests"
        )

        # Auto-inject storage and model into request_builder kwargs
        builder_kwargs = {
            'storage': self.storage,
            'model': self.model,
            **request_builder_kwargs  # Allow overrides
        }

        requests = []
        for prepared, item in enumerate(items, 1):
            try:
                request = self.request_builder(item=item, **builder_kwargs)
                if request:
                    requests.append(request)
            except Exception as e:
                self.logger.warning(f"Failed to prepare item {item}", error=str(e))

            prep_progress.update(prepared, suffix=f"{prepared}/{len(items)} prepared")

        prep_elapsed = time.time() - prep_start
        prep_progress.finish(f"✅ Prepared {len(requests)} requests in {prep_elapsed:.1f}s")
        self.logger.info(f"{self.batch_name}: Prepared {len(requests)}/{len(items)} requests in {prep_elapsed:.1f}s")

        if not requests:
            self.logger.error(f"{self.batch_name}: No valid requests prepared")
            return BatchStats()

        progress = RichProgressBarHierarchical(
            total=len(requests),
            prefix="   ",
            width=40,
            unit="items",
        )
        progress.update(0, suffix="starting...")

        progress_handler = create_progress_handler(
            progress_bar=progress,
            worker_pool=self.batch_client.worker_pool,
            rate_limiter=self.batch_client.rate_limiter,
            metrics_manager=self.metrics_manager,
            total_requests=len(requests),
            start_time=start_time,
            batch_start_time=self.batch_client.batch_start_time or start_time
        )

        stop_polling = threading.Event()

        def poll_progress():
            while not stop_polling.is_set():
                try:
                    progress_handler()

                    rate_limit_status = self.batch_client.rate_limiter.get_status()
                    if rate_limit_status.get('paused', False):
                        wait_seconds = rate_limit_status.get('wait_seconds', 0)
                        progress.set_status(f"⏸️  Rate limited, resuming in {wait_seconds:.0f}s")
                except Exception as e:
                    self.logger.debug(f"Progress polling error: {e}")

                time.sleep(1.0)

        poll_thread = threading.Thread(target=poll_progress, daemon=True)
        poll_thread.start()

        try:
            self.batch_client.process_batch(
                requests,
                on_result=self.result_handler,
            )
        finally:
            stop_polling.set()
            poll_thread.join(timeout=2.0)

            elapsed = time.time() - start_time
            batch_stats = self.get_batch_stats(total_items=len(items))

            display_summary(
                progress_bar=progress,
                batch_name=self.batch_name,
                batch_stats=batch_stats,
                elapsed=elapsed,
                total_items=len(items),
                metrics_manager=self.metrics_manager,
                metric_prefix=self.metric_prefix
            )

            self.logger.info(
                f"{self.batch_name} complete: {batch_stats.completed} completed, "
                f"{batch_stats.failed} failed, "
                f"${batch_stats.total_cost_usd:.4f}"
            )

        return batch_stats