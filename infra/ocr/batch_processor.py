import time
from typing import Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image
import json
from pathlib import Path

from rich.progress import Progress, BarColumn, TextColumn, TaskProgressColumn, TimeRemainingColumn
from rich.console import Console

from infra.llm.rate_limiter import RateLimiter
from infra.llm.batch.progress.display import format_batch_summary
from .config import OCRBatchConfig


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
    def __init__(self, config: OCRBatchConfig):
        self.config = config
        self.provider = config.provider
        self.tracker = config.tracker
        self.storage = config.tracker.storage
        self.logger = config.tracker.logger
        self.max_workers = config.max_workers
        self.batch_name = config.batch_name or config.provider.name

        self.stage_storage = config.tracker.stage_storage
        self.subdir = config.tracker.phase_name
        self.metrics_manager = config.tracker.metrics_manager
        self.metrics_prefix = config.tracker.metrics_prefix

        if self.provider.requests_per_second != float('inf'):
            requests_per_minute = int(self.provider.requests_per_second * 60)
            self.rate_limiter = RateLimiter(requests_per_minute=requests_per_minute)
        else:
            self.rate_limiter = None

    def process_batch(self) -> Dict[str, Any]:
        page_nums = self.tracker.get_remaining_items()

        source_storage = self.storage.stage("source")
        logs_dir = self.tracker.phase_dir / "logs"

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

        self.logger.info(f"Processing {len(page_nums)} pages with {self.provider.name}")
        self.logger.info(f"Workers: {self.max_workers}, Rate limit: {rate_limit_str}")

        progress = Progress(
            TextColumn("   {task.description}"),
            BarColumn(bar_width=40),
            TaskProgressColumn(),
            TextColumn("•"),
            TimeRemainingColumn(),
            TextColumn("•"),
            TextColumn("{task.fields[suffix]}", justify="right"),
            transient=True
        )

        def process_single_page(page_num: int) -> Dict[str, Any]:
            nonlocal pages_processed, total_cost, total_chars, total_time

            page_file = source_storage.output_dir / f"page_{page_num:04d}.png"

            if not page_file.exists():
                error_msg = f"Source image not found: {page_file}"
                self.logger.error(f"  Page {page_num}: {error_msg}")
                _log_failure(logs_dir, page_num, error_msg, attempt=0, max_retries=self.provider.max_retries)
                return {"success": False, "page_num": page_num, "error": error_msg}

            try:
                image = Image.open(page_file)
            except Exception as e:
                error_msg = f"Failed to load image: {e}"
                self.logger.error(f"  Page {page_num}: {error_msg}")
                _log_failure(logs_dir, page_num, error_msg, attempt=0, max_retries=self.provider.max_retries)
                return {"success": False, "page_num": page_num, "error": error_msg}

            result = None
            for attempt in range(self.provider.max_retries + 1):
                try:
                    if self.rate_limiter:
                        self.rate_limiter.consume()

                    result = self.provider.process_image(image, page_num)

                    if result.success:
                        result.retry_count = attempt
                        break
                    else:
                        if attempt < self.provider.max_retries:
                            delay = self.provider.retry_delay_base ** attempt
                            time.sleep(delay)
                            continue
                        else:
                            _log_failure(logs_dir, page_num, result.error_message, attempt, self.provider.max_retries)
                            return {"success": False, "page_num": page_num, "error": result.error_message}

                except Exception as e:
                    error_msg = str(e)
                    if attempt < self.provider.max_retries:
                        delay = self.provider.retry_delay_base ** attempt
                        time.sleep(delay)
                        continue
                    else:
                        _log_failure(logs_dir, page_num, error_msg, attempt, self.provider.max_retries)
                        return {"success": False, "page_num": page_num, "error": error_msg}

            if result and result.success:
                self.provider.handle_result(page_num, result, subdir=self.subdir, metrics_prefix=self.metrics_prefix)

                pages_processed += 1
                total_cost += result.cost_usd
                total_chars += len(result.text)
                total_time += result.execution_time_seconds

                return {"success": True, "page_num": page_num}
            else:
                return {"success": False, "page_num": page_num, "error": "Unknown error"}

        with progress:
            task_id = progress.add_task("", total=len(page_nums), suffix="starting...")

            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {executor.submit(process_single_page, page_num): page_num for page_num in page_nums}

                for future in as_completed(futures):
                    result = future.result()
                    if not result["success"]:
                        failed_pages.append(result["page_num"])

                    avg_time = total_time / pages_processed if pages_processed > 0 else 0
                    progress.update(
                        task_id,
                        completed=pages_processed + len(failed_pages),
                        suffix=f"{pages_processed}/{len(page_nums)} • ${total_cost:.4f} • {avg_time:.1f}s/pg"
                    )

        summary_text = format_batch_summary(
            batch_name=self.batch_name,
            completed=pages_processed,
            total=len(page_nums),
            time_seconds=total_time,
            prompt_tokens=0,
            completion_tokens=0,
            reasoning_tokens=0,
            cost_usd=total_cost,
            unit="pages"
        )
        Console().print(summary_text)

        self.logger.info(
            f"{self.batch_name} complete: {pages_processed}/{len(page_nums)} pages, "
            f"${total_cost:.4f}, {total_chars:,} chars"
        )

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
