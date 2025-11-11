"""
Generic OCR batch processor for parallel page processing.

Handles:
- Parallel processing with ThreadPoolExecutor
- Automatic rate limiting (requests/second)
- Retry logic with exponential backoff
- Progress tracking with rich progress bar
- Failure logging
- Metrics aggregation

Works with any OCRProvider implementation.
"""

import time
from pathlib import Path
from typing import List, Dict, Any, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image
import json

from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.llm.rate_limiter import RateLimiter
from infra.pipeline.rich_progress import RichProgressBar
from .provider import OCRProvider, OCRResult


def _log_failure(storage: BookStorage, page_num: int, error: str, attempt: int, max_retries: int):
    """
    Log OCR failure to logs/llm_failures.json.

    Args:
        storage: Stage storage for log directory
        page_num: Page that failed
        error: Error message
        attempt: Retry attempt number (0-indexed)
        max_retries: Maximum retries configured
    """
    logs_dir = storage.output_dir / "logs"
    logs_dir.mkdir(exist_ok=True)
    failure_log = logs_dir / "llm_failures.json"

    failure_entry = {
        "page_num": page_num,
        "error": error,
        "attempt": attempt,
        "max_retries": max_retries,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }

    # Append to existing log file
    if failure_log.exists():
        with open(failure_log, 'r') as f:
            failures = json.load(f)
    else:
        failures = []

    failures.append(failure_entry)

    with open(failure_log, 'w') as f:
        json.dump(failures, f, indent=2)


class OCRBatchProcessor:
    """
    Generic batch processor for any OCR provider.

    Standardizes:
    - Parallel processing (ThreadPoolExecutor)
    - Rate limiting (configurable per provider)
    - Retry with exponential backoff
    - Progress display (RichProgressBar)
    - Failure logging
    - Metrics aggregation
    """

    def __init__(
        self,
        provider: OCRProvider,
        status_tracker,
        max_workers: int = 10,
    ):
        """
        Initialize OCR batch processor.

        Args:
            provider: OCR provider implementation
            status_tracker: BatchBasedStatusTracker with storage, logger, stage info
            max_workers: Thread pool size
        """
        self.provider = provider
        self.status_tracker = status_tracker
        self.storage = status_tracker.storage
        self.logger = status_tracker.logger
        self.max_workers = max_workers

        # Set up rate limiter if provider has limit
        if provider.requests_per_second != float('inf'):
            requests_per_minute = int(provider.requests_per_second * 60)
            self.rate_limiter = RateLimiter(requests_per_minute=requests_per_minute)
        else:
            self.rate_limiter = None

    def process_batch(self) -> Dict[str, Any]:
        """
        Process batch of remaining pages with automatic retry, rate limiting, and progress tracking.

        Gets remaining pages from status tracker.

        Returns:
            Batch statistics:
            {
                "status": "success" | "partial" | "failed",
                "pages_processed": int,
                "total_cost": float,
                "total_chars": int,
                "total_time": float,
                "failed_pages": List[int]
            }
        """
        # Get remaining pages from status tracker
        page_nums = self.status_tracker.get_remaining_items()

        source_storage = self.storage.stage("source")
        stage_storage = self.storage.stage(self.provider.name)

        # Statistics tracking
        pages_processed = 0
        total_cost = 0.0
        total_chars = 0
        total_time = 0.0
        failed_pages = []

        # Log initialization (mistral-ocr style)
        rate_limit_str = (
            f"{self.provider.requests_per_second:.1f} req/sec"
            if self.provider.requests_per_second != float('inf')
            else "unlimited"
        )

        self.logger.info(f"=== {self.provider.name.upper()} OCR: Processing {len(page_nums)} pages ===")
        self.logger.info(f"Provider: {self.provider.name}")
        self.logger.info(f"Workers: {self.max_workers}")
        self.logger.info(f"Rate limit: {rate_limit_str}")
        self.logger.info(f"Max retries: {self.provider.max_retries}")

        # Progress bar
        progress = RichProgressBar(
            total=len(page_nums),
            prefix=f"  {self.provider.name}-ocr"
        )

        def process_single_page(page_num: int) -> Dict[str, Any]:
            """Process a single page with retry logic."""
            nonlocal pages_processed, total_cost, total_chars, total_time

            page_file = source_storage.output_dir / f"page_{page_num:04d}.png"

            # Check if source image exists
            if not page_file.exists():
                error_msg = f"Source image not found: {page_file}"
                self.logger.error(f"  Page {page_num}: {error_msg}")
                _log_failure(stage_storage, page_num, error_msg, attempt=0, max_retries=self.provider.max_retries)
                return {"success": False, "page_num": page_num, "error": error_msg}

            # Load image
            try:
                image = Image.open(page_file)
            except Exception as e:
                error_msg = f"Failed to load image: {e}"
                self.logger.error(f"  Page {page_num}: {error_msg}")
                _log_failure(stage_storage, page_num, error_msg, attempt=0, max_retries=self.provider.max_retries)
                return {"success": False, "page_num": page_num, "error": error_msg}

            # Retry loop with exponential backoff
            result = None
            for attempt in range(self.provider.max_retries + 1):
                try:
                    # Rate limiting
                    if self.rate_limiter:
                        self.rate_limiter.consume()

                    # Call provider
                    result = self.provider.process_image(image, page_num)

                    # Check if successful
                    if result.success:
                        result.retry_count = attempt
                        break
                    else:
                        # Provider returned failure, retry if attempts remain
                        if attempt < self.provider.max_retries:
                            delay = self.provider.retry_delay_base ** attempt
                            time.sleep(delay)
                            continue
                        else:
                            # Out of retries
                            _log_failure(stage_storage, page_num, result.error_message, attempt, self.provider.max_retries)
                            return {"success": False, "page_num": page_num, "error": result.error_message}

                except Exception as e:
                    error_msg = str(e)
                    if attempt < self.provider.max_retries:
                        # Retry after backoff
                        delay = self.provider.retry_delay_base ** attempt
                        time.sleep(delay)
                        continue
                    else:
                        # Out of retries
                        _log_failure(stage_storage, page_num, error_msg, attempt, self.provider.max_retries)
                        return {"success": False, "page_num": page_num, "error": error_msg}

            # Success - let provider handle result (save + metrics)
            if result and result.success:
                self.provider.handle_result(page_num, result)

                # Update aggregates
                pages_processed += 1
                total_cost += result.cost_usd
                total_chars += len(result.text)
                total_time += result.execution_time_seconds

                # Update progress bar
                avg_time = total_time / pages_processed if pages_processed > 0 else 0
                progress.update(
                    pages_processed,
                    suffix=f"{pages_processed}/{len(page_nums)} • ${total_cost:.4f} • {total_chars:,} chars • {avg_time:.1f}s/page"
                )

                return {"success": True, "page_num": page_num}
            else:
                return {"success": False, "page_num": page_num, "error": "Unknown error"}

        # Process pages in parallel
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(process_single_page, page_num): page_num for page_num in page_nums}

            for future in as_completed(futures):
                result = future.result()
                if not result["success"]:
                    failed_pages.append(result["page_num"])

        # Finish progress bar
        progress.finish()

        # Log completion summary (mistral-ocr style)
        summary_lines = [
            "",
            "=" * 80,
            f"{self.provider.name.upper()} OCR Complete",
            "=" * 80,
            f"Pages processed: {pages_processed}/{len(page_nums)}" + (f" ({len(failed_pages)} failed)" if failed_pages else ""),
            f"Total cost:     ${total_cost:.4f}",
            f"Total chars:    {total_chars:,}",
            f"Total time:     {total_time:.1f}s",
        ]

        if pages_processed > 0:
            summary_lines.append(f"Avg time/page:  {total_time / pages_processed:.1f}s")

        if self.rate_limiter:
            wait_stats = self.rate_limiter.get_status()
            if wait_stats['total_waited_sec'] > 0:
                summary_lines.append(f"Rate limit wait: {wait_stats['total_waited_sec']:.1f}s")

        summary_lines.append("=" * 80)

        # Log to both progress bar display and file
        summary_text = "\n".join(summary_lines)
        self.logger.info(summary_text)

        # Determine status
        if pages_processed == len(page_nums):
            status = "success"
        elif pages_processed > 0:
            status = "partial"
        else:
            status = "failed"

        return {
            "status": status,
            "pages_processed": pages_processed,
            "total_cost": total_cost,
            "total_chars": total_chars,
            "total_time": total_time,
            "failed_pages": failed_pages
        }
