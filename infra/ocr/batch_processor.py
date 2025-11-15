import time
from typing import Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image
import json
from pathlib import Path

from infra.llm.rate_limiter import RateLimiter
from rich.progress import Progress, BarColumn, TextColumn, TaskProgressColumn, TimeRemainingColumn
from .provider import OCRProvider


def _log_failure(logs_dir: Path, page_num: int, error: str, attempt: int, max_retries: int):
    logs_dir.mkdir(parents=True, exist_ok=True)
    failure_log = logs_dir / "llm_failures.json"

    failure_entry = {
        "page_num": page_num,
        "error": error,
        "attempt": attempt,
        "max_retries": max_retries,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }

    if failure_log.exists():
        with open(failure_log, 'r') as f:
            failures = json.load(f)
    else:
        failures = []

    failures.append(failure_entry)

    with open(failure_log, 'w') as f:
        json.dump(failures, f, indent=2)


class OCRBatchProcessor:
    def __init__(
        self,
        provider: OCRProvider,
        status_tracker,
        max_workers: int = 10,
    ):
        self.provider = provider
        self.status_tracker = status_tracker
        self.storage = status_tracker.storage
        self.logger = status_tracker.logger
        self.max_workers = max_workers

        # Use tracker's stage_storage and phase_dir
        self.stage_storage = status_tracker.stage_storage
        self.output_dir = status_tracker.phase_dir
        self.metrics_manager = status_tracker.metrics_manager
        self.metrics_prefix = status_tracker.metrics_prefix

        if provider.requests_per_second != float('inf'):
            requests_per_minute = int(provider.requests_per_second * 60)
            self.rate_limiter = RateLimiter(requests_per_minute=requests_per_minute)
        else:
            self.rate_limiter = None

    def process_batch(self) -> Dict[str, Any]:
        page_nums = self.status_tracker.get_remaining_items()

        source_storage = self.storage.stage("source")
        # Use tracker's output_dir instead of assuming stage name
        logs_dir = self.output_dir / "logs"

        pages_processed = 0
        total_cost = 0.0
        total_chars = 0
        total_time = 0.0
        failed_pages = []

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

        progress = Progress(
            TextColumn(f"{self.provider.name}-ocr{{task.description}}"),
            BarColumn(bar_width=40),
            TaskProgressColumn(),
            TextColumn("•"),
            TimeRemainingColumn(),
            TextColumn("•"),
            TextColumn("{task.fields[suffix]}", justify="right"),
            transient=True
        )
        progress.__enter__()
        task_id = progress.add_task("", total=len(page_nums), suffix="")

        def process_single_page(page_num: int) -> Dict[str, Any]:
            nonlocal pages_processed, total_cost, total_chars, total_time

            page_file = source_storage.output_dir / f"page_{page_num:04d}.png"

            if not page_file.exists():
                error_msg = f"Source image not found: {page_file}"
                self.logger.error(f"  Page {page_num}: {error_msg}")
                _log_failure(logs_dir, page_num, error_msg, attempt=0, max_retries=self.provider.max_retries)
                return {"success": False, "page_num": page_num, "error": error_msg}

            # Load image
            try:
                image = Image.open(page_file)
            except Exception as e:
                error_msg = f"Failed to load image: {e}"
                self.logger.error(f"  Page {page_num}: {error_msg}")
                _log_failure(logs_dir, page_num, error_msg, attempt=0, max_retries=self.provider.max_retries)
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
                            _log_failure(logs_dir, page_num, result.error_message, attempt, self.provider.max_retries)
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
                        _log_failure(logs_dir, page_num, error_msg, attempt, self.provider.max_retries)
                        return {"success": False, "page_num": page_num, "error": error_msg}

            # Success - let provider handle result (save + metrics)
            if result and result.success:
                # Pass output_dir to provider so it writes to correct location
                self.provider.handle_result(page_num, result, output_dir=self.output_dir)

                # Update aggregates
                pages_processed += 1
                total_cost += result.cost_usd
                total_chars += len(result.text)
                total_time += result.execution_time_seconds

                # Update progress bar
                avg_time = total_time / pages_processed if pages_processed > 0 else 0
                progress.update(
                    task_id,
                    completed=pages_processed,
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
        progress.__exit__(None, None, None)

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
