import os
import time
import threading
from typing import List
from concurrent.futures import ThreadPoolExecutor, as_completed

from .client import LLMBatchClient
from .progress import create_progress_handler
from .progress.display import display_summary
from .schemas import BatchStats, LLMBatchConfig
from rich.progress import Progress, BarColumn, TextColumn, TaskProgressColumn, TimeRemainingColumn


class LLMBatchProcessor:
    def __init__(self, config: LLMBatchConfig):
        self.config = config
        self.tracker = config.tracker
        self.logger = config.tracker.logger
        self.storage = config.tracker.storage

        # PhaseStatusTracker provides all we need
        self.stage_name = config.tracker.phase_name
        self.metrics_manager = config.tracker.metrics_manager
        self.metric_prefix = config.tracker.metrics_prefix

        self.model = config.model
        self.max_workers = config.max_workers or 30
        self.max_retries = config.max_retries
        self.retry_jitter = config.retry_jitter
        self.batch_name = config.batch_name
        self.request_builder = config.request_builder
        self.result_handler = config.result_handler

        self.batch_client = LLMBatchClient(
            model=self.model,  # Pass model to batch client
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
            batch_start_time=self.batch_client.batch_start_time or time.time(),
            metric_prefix=self.metric_prefix
        )

    def process(
        self,
        **request_builder_kwargs
    ) -> BatchStats:
        items = self.tracker.get_remaining_items()

        if not items:
            self.logger.info(f"{self.batch_name}: No items to process")
            return BatchStats()

        self.logger.info(f"{self.batch_name}: Processing {len(items)} items...")
        start_time = time.time()

        prep_start = time.time()
        prep_progress = Progress(
            TextColumn("{task.description}"),
            BarColumn(bar_width=40),
            TaskProgressColumn(),
            TextColumn("{task.fields[suffix]}", justify="right"),
            transient=True
        )

        builder_kwargs = {
            'storage': self.storage,
            **request_builder_kwargs  # Allow overrides
        }

        def prepare_single(item):
            """Prepare one request (called in parallel)."""
            try:
                request = self.request_builder(item=item, **builder_kwargs)
                return request
            except Exception as e:
                self.logger.warning(f"Failed to prepare item {item}", error=str(e))
                return None

        requests = []
        with prep_progress:
            prep_task = prep_progress.add_task("", total=len(items), suffix="loading...")
            prepared = 0

            # Parallel preparation using thread pool (CPU-bound: image loading/processing)
            # Use CPU count * 2 for preparation, separate from network I/O workers
            prep_workers = os.cpu_count() * 4 if os.cpu_count() else 8
            with ThreadPoolExecutor(max_workers=prep_workers) as executor:
                futures = {executor.submit(prepare_single, item): item for item in items}
                for future in as_completed(futures):
                    request = future.result()
                    if request:
                        requests.append(request)

                    prepared += 1
                    prep_progress.update(prep_task, completed=prepared, suffix=f"{prepared}/{len(items)} prepared")

        prep_elapsed = time.time() - prep_start
        print(f"✅ Prepared {len(requests)} requests in {prep_elapsed:.1f}s")
        self.logger.info(f"{self.batch_name}: Prepared {len(requests)}/{len(items)} requests in {prep_elapsed:.1f}s")

        if not requests:
            self.logger.error(f"{self.batch_name}: No valid requests prepared")
            return BatchStats()

        progress = Progress(
            TextColumn("   {task.description}"),
            BarColumn(bar_width=40),
            TaskProgressColumn(),
            TextColumn("{task.fields[suffix]}", justify="right"),
            transient=True
        )
        progress.__enter__()
        progress_task = progress.add_task("", total=len(requests), suffix="starting...")

        progress_handler = create_progress_handler(
            progress_bar=progress,
            progress_task=progress_task,
            worker_pool=self.batch_client.worker_pool,
            rate_limiter=self.batch_client.rate_limiter,
            metrics_manager=self.metrics_manager,
            total_requests=len(requests),
            start_time=start_time,
            batch_start_time=self.batch_client.batch_start_time or start_time,
            metric_prefix=self.metric_prefix
        )

        stop_polling = threading.Event()

        def poll_progress():
            while not stop_polling.is_set():
                try:
                    progress_handler()

                    rate_limit_status = self.batch_client.rate_limiter.get_status()
                    if rate_limit_status.get('paused', False):
                        wait_seconds = rate_limit_status.get('wait_seconds', 0)
                        progress.update(progress_task, description=f"⏸️  Rate limited, resuming in {wait_seconds:.0f}s")
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

            progress.__exit__(None, None, None)

            # Get accurate totals from tracker status (source of truth)
            tracker_status = self.tracker.get_status()
            total_items = tracker_status['progress']['total_items']
            completed_items = tracker_status['progress']['completed_items']

            display_summary(
                batch_name=self.batch_name,
                batch_stats=batch_stats,
                elapsed=elapsed,
                total_items=total_items,
                completed_items=completed_items,
                metrics_manager=self.metrics_manager,
                metric_prefix=self.metric_prefix
            )

            self.logger.info(
                f"{self.batch_name} complete: {batch_stats.completed} completed, "
                f"{batch_stats.failed} failed, "
                f"${batch_stats.total_cost_usd:.4f}"
            )

        return batch_stats