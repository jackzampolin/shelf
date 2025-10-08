#!/usr/bin/env python3
"""
Unified parallelization utilities for pipeline stages.

Provides consistent patterns for:
- ThreadPoolExecutor setup
- Progress tracking
- Error handling
- Rate limiting (for LLM calls)
- Checkpoint integration
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List, Dict, Any, Optional
from pathlib import Path
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from platform.logger import PipelineLogger


class RateLimiter:
    """Thread-safe rate limiter for API calls."""

    def __init__(self, calls_per_minute: int = 150):
        """
        Initialize rate limiter.

        Args:
            calls_per_minute: Maximum API calls per minute
        """
        self.calls_per_minute = calls_per_minute
        self.min_interval = 60.0 / calls_per_minute
        self.last_call = 0
        self.lock = threading.Lock()

    def wait(self):
        """Wait if necessary to respect rate limit."""
        with self.lock:
            now = time.time()
            time_since_last = now - self.last_call
            if time_since_last < self.min_interval:
                sleep_time = self.min_interval - time_since_last
                time.sleep(sleep_time)
            self.last_call = time.time()


class ParallelProcessor:
    """
    Unified parallel processing with progress tracking, rate limiting, and checkpoints.

    Features:
    - ThreadPoolExecutor management
    - Progress logging at configurable intervals
    - Optional rate limiting for LLM API calls
    - Optional checkpoint integration for resumability
    - Thread-safe statistics tracking
    - Consistent error handling

    Usage:
        processor = ParallelProcessor(
            max_workers=30,
            rate_limit=150,
            logger=logger,
            checkpoint=checkpoint,
            description="Processing pages"
        )

        results = processor.process(
            items=pages,
            worker_func=process_page,
            progress_interval=50
        )
    """

    def __init__(
        self,
        max_workers: int = 30,
        rate_limit: Optional[int] = None,
        logger: Optional[PipelineLogger] = None,
        description: str = "Processing",
        progress_callback: Optional[Callable[[int, int], None]] = None,
        result_callback: Optional[Callable[[Any], None]] = None
    ):
        """
        Initialize parallel processor.

        Args:
            max_workers: Maximum number of concurrent workers
            rate_limit: Optional API calls per minute limit
            logger: Optional logger instance for progress tracking
            description: Human-readable description for logging
            progress_callback: Optional callback(completed, total) called on progress updates
            result_callback: Optional callback(result) called for each completed item
        """
        self.max_workers = max_workers
        self.rate_limiter = RateLimiter(rate_limit) if rate_limit else None
        self.logger = logger
        self.description = description
        self.progress_callback = progress_callback
        self.result_callback = result_callback

        # Thread-safe stats
        self.stats_lock = threading.Lock()
        self.stats = {
            "processed": 0,
            "succeeded": 0,
            "failed": 0,
            "total_cost": 0.0
        }

    def process(
        self,
        items: List[Any],
        worker_func: Callable,
        progress_interval: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Process items in parallel with unified progress tracking.

        Args:
            items: List of items to process
            worker_func: Function that processes one item, returns dict with 'result' and optional 'cost'
            progress_interval: Log progress every N items

        Returns:
            List of results from worker_func
        """
        items_to_process = items

        total = len(items_to_process)

        if total == 0:
            if self.logger:
                self.logger.info(f"{self.description}: No items to process")
            return []

        if self.logger:
            self.logger.info(
                f"{self.description}: {total} items, {self.max_workers} workers"
            )

        results = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all tasks
            futures = {
                executor.submit(self._wrapped_worker, worker_func, item): item
                for item in items_to_process
            }

            # Collect results
            for future in as_completed(futures):
                item = futures[future]
                try:
                    result = future.result()
                    results.append(result)

                    # Update stats
                    with self.stats_lock:
                        self.stats["processed"] += 1
                        self.stats["succeeded"] += 1
                        if "cost" in result:
                            self.stats["total_cost"] += result.get("cost", 0.0)

                    # Call result callback immediately (for incremental saves)
                    if self.result_callback:
                        self.result_callback(result)

                    # Progress logging and callback
                    if self.stats["processed"] % progress_interval == 0:
                        if self.logger:
                            self.logger.info(
                                f"Progress: {self.stats['processed']}/{total} items processed"
                            )
                        # Call progress callback for checkpoint updates
                        if self.progress_callback:
                            self.progress_callback(self.stats["processed"], total)

                except Exception as e:
                    with self.stats_lock:
                        self.stats["processed"] += 1
                        self.stats["failed"] += 1

                    if self.logger:
                        self.logger.error(f"Error processing item: {e}")

        if self.logger:
            self.logger.info(
                f"{self.description} complete: {self.stats['succeeded']} succeeded, "
                f"{self.stats['failed']} failed, cost: ${self.stats['total_cost']:.4f}"
            )

        return results

    def _wrapped_worker(self, worker_func: Callable, item: Any) -> Dict[str, Any]:
        """
        Wrapper that adds rate limiting if configured.

        Args:
            worker_func: The actual worker function
            item: Item to process

        Returns:
            Result from worker_func
        """
        if self.rate_limiter:
            self.rate_limiter.wait()

        return worker_func(item)
