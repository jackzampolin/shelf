import os
import time
import threading
from typing import List
from concurrent.futures import ThreadPoolExecutor, as_completed

from .client import LLMBatchClient
from .progress import create_progress_handler
from .schemas import BatchStats, LLMBatchConfig
from rich.progress import Progress, BarColumn, TextColumn, TaskProgressColumn
from infra.llm.display import DisplayStats, print_phase_complete


def is_headless():
    """Check if running in headless mode (no Rich displays)."""
    return os.environ.get('SHELF_HEADLESS', '').lower() in ('1', 'true', 'yes')


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

        # Parallel preparation using thread pool (CPU-bound: image loading/processing)
        # Use CPU count * 2 for preparation, separate from network I/O workers
        prep_workers = os.cpu_count() * 4 if os.cpu_count() else 8

        if is_headless():
            # No progress display in headless mode
            with ThreadPoolExecutor(max_workers=prep_workers) as executor:
                futures = {executor.submit(prepare_single, item): item for item in items}
                for future in as_completed(futures):
                    request = future.result()
                    if request:
                        requests.append(request)
        else:
            # Preparation progress bar with hourglass
            prep_progress = Progress(
                TextColumn(f"⏳ {self.batch_name} (preparing)"),
                BarColumn(bar_width=40),
                TaskProgressColumn(),
                TextColumn("{task.fields[suffix]}", justify="right"),
                transient=True
            )
            with prep_progress:
                prep_task = prep_progress.add_task("", total=len(items), suffix="")
                prepared = 0

                with ThreadPoolExecutor(max_workers=prep_workers) as executor:
                    futures = {executor.submit(prepare_single, item): item for item in items}
                    for future in as_completed(futures):
                        request = future.result()
                        if request:
                            requests.append(request)

                        prepared += 1
                        prep_progress.update(prep_task, completed=prepared, suffix=f"{prepared}/{len(items)}")

        prep_elapsed = time.time() - prep_start
        self.logger.info(f"{self.batch_name}: Prepared {len(requests)}/{len(items)} requests in {prep_elapsed:.1f}s")

        if not requests:
            self.logger.error(f"{self.batch_name}: No valid requests prepared")
            return BatchStats()

        # Get phase totals for progress display (show full phase progress)
        tracker_status = self.tracker.get_status()
        total_items_in_phase = tracker_status['progress']['total_items']
        already_completed = tracker_status['progress']['completed_items']

        if is_headless():
            # No progress display in headless mode - just run batch processing
            try:
                self.batch_client.process_batch(
                    requests,
                    on_result=self.result_handler,
                )
            finally:
                elapsed = time.time() - start_time
                batch_stats = self.get_batch_stats(total_items=len(items))

                # Get accurate totals from tracker status (source of truth)
                tracker_status = self.tracker.get_status()
                total_items = tracker_status['progress']['total_items']
                completed_items = tracker_status['progress']['completed_items']

                # Get cumulative metrics for accurate token counts
                cumulative = self.metrics_manager.get_cumulative_metrics(prefix=self.metric_prefix)

                print_phase_complete(self.batch_name, DisplayStats(
                    completed=completed_items,
                    total=total_items,
                    time_seconds=elapsed,
                    prompt_tokens=cumulative.get('total_prompt_tokens', batch_stats.total_prompt_tokens),
                    completion_tokens=cumulative.get('total_completion_tokens', batch_stats.total_completion_tokens),
                    reasoning_tokens=cumulative.get('total_reasoning_tokens', batch_stats.total_reasoning_tokens),
                    cost_usd=cumulative.get('total_cost_usd', batch_stats.total_cost_usd),
                ))

                self.logger.info(
                    f"{self.batch_name} complete: {batch_stats.completed} completed, "
                    f"{batch_stats.failed} failed, "
                    f"${batch_stats.total_cost_usd:.4f}"
                )

            return batch_stats

        # Normal mode with progress display
        # Show full phase progress: start at already_completed, go to total_items_in_phase
        progress = Progress(
            TextColumn(f"⏳ {self.batch_name}"),
            BarColumn(bar_width=40),
            TaskProgressColumn(),
            TextColumn("{task.fields[suffix]}", justify="right"),
            transient=True
        )
        progress.__enter__()
        progress_task = progress.add_task(
            "",
            total=total_items_in_phase,
            completed=already_completed,
            suffix=f"{already_completed}/{total_items_in_phase}"
        )

        progress_handler = create_progress_handler(
            progress_bar=progress,
            progress_task=progress_task,
            worker_pool=self.batch_client.worker_pool,
            rate_limiter=self.batch_client.rate_limiter,
            metrics_manager=self.metrics_manager,
            total_requests=total_items_in_phase,
            start_time=start_time,
            batch_start_time=self.batch_client.batch_start_time or start_time,
            metric_prefix=self.metric_prefix,
            tracker=self.tracker,
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

            # Get cumulative metrics for accurate token counts
            cumulative = self.metrics_manager.get_cumulative_metrics(prefix=self.metric_prefix)

            print_phase_complete(self.batch_name, DisplayStats(
                completed=completed_items,
                total=total_items,
                time_seconds=elapsed,
                prompt_tokens=cumulative.get('total_prompt_tokens', batch_stats.total_prompt_tokens),
                completion_tokens=cumulative.get('total_completion_tokens', batch_stats.total_completion_tokens),
                reasoning_tokens=cumulative.get('total_reasoning_tokens', batch_stats.total_reasoning_tokens),
                cost_usd=cumulative.get('total_cost_usd', batch_stats.total_cost_usd),
            ))

            self.logger.info(
                f"{self.batch_name} complete: {batch_stats.completed} completed, "
                f"{batch_stats.failed} failed, "
                f"${batch_stats.total_cost_usd:.4f}"
            )

        return batch_stats