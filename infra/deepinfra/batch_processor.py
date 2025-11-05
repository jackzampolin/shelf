"""
DeepInfra OCR batch processor with concurrent execution and progress tracking.

Provides parallel OCR processing for multiple pages with:
- Concurrent execution via ThreadPoolExecutor
- Progress bar with per-page token/cost tracking
- Event callbacks for result handling
- Aggregate batch statistics

Similar to infra/llm/batch_processor.py but specialized for DeepInfra OCR calls.
"""

import time
from pathlib import Path
from typing import List, Dict, Any, Callable, Optional
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image

from infra.pipeline.logger import PipelineLogger
from infra.pipeline.rich_progress import RichProgressBarHierarchical
from infra.llm.display_format import format_batch_summary
from infra.config import Config
from .ocr import OlmOCRProvider


@dataclass
class OCRRequest:
    """
    Container for a single OCR request.

    Attributes:
        id: Unique identifier (e.g., "page_004")
        image: PIL Image to process
        prompt: OCR prompt (e.g., "Extract all text...")
        metadata: User-defined metadata (passed through to result)
    """
    id: str
    image: Image.Image
    prompt: str = "Free OCR"
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class OCRResult:
    """
    Container for OCR response with telemetry.

    Attributes:
        request_id: ID from the original request
        success: Whether OCR succeeded
        text: Extracted text (if successful)
        error_message: Error message (if failed)

        # Telemetry
        execution_time_seconds: Time spent in OCR call
        prompt_tokens: Prompt tokens used
        completion_tokens: Completion tokens used
        cost_usd: Cost in USD

        # Original request (for context)
        request: Original OCRRequest
    """
    request_id: str
    success: bool
    text: Optional[str] = None
    error_message: Optional[str] = None

    # Telemetry
    execution_time_seconds: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0

    # Reference to original request
    request: Optional[OCRRequest] = None


class DeepInfraOCRBatchProcessor:
    """
    Batch processor for parallel OCR requests.

    Similar to LLMBatchProcessor but simplified for OCR:
    - No retries (OCR is fast, fail-fast is better)
    - No rate limiting (DeepInfra handles this)
    - Simple ThreadPoolExecutor (no queue management)
    - Progress bar shows per-page completion

    Usage:
        processor = DeepInfraOCRBatchProcessor(
            logger=logger,
            max_workers=4
        )

        def handle_result(result: OCRResult):
            if result.success:
                save_text(result.text)
            else:
                logger.error(f"OCR failed: {result.error_message}")

        stats = processor.process_batch(
            requests=requests,
            on_result=handle_result
        )
    """

    def __init__(
        self,
        logger: PipelineLogger,
        max_workers: Optional[int] = None,
        verbose: bool = True,
        batch_name: str = "OCR"
    ):
        """
        Initialize OCR batch processor.

        Args:
            logger: PipelineLogger instance
            max_workers: Thread pool size (default: Config.max_workers)
            verbose: Enable progress display
            batch_name: Display name for progress/summary (e.g., "OCR", "Text extraction")
        """
        self.logger = logger
        self.max_workers = max_workers or Config.max_workers
        self.verbose = verbose
        self.batch_name = batch_name

        # Create OCR provider (thread-safe)
        self.ocr_provider = OlmOCRProvider()

    def process_batch(
        self,
        requests: List[OCRRequest],
        on_result: Callable[[OCRResult], None]
    ) -> Dict[str, Any]:
        """
        Process a batch of OCR requests with progress tracking.

        Args:
            requests: List of OCR requests to process
            on_result: Callback for each completed request
                      Signature: (result: OCRResult) -> None
                      Caller handles parsing, validation, persistence

        Returns:
            Stats dict with:
            - completed: Number of successful requests
            - failed: Number of failed requests
            - total_cost_usd: Total cost in USD
            - total_tokens: Total tokens processed
            - elapsed_seconds: Total elapsed time
        """
        if not requests:
            return {
                "completed": 0,
                "failed": 0,
                "total_cost_usd": 0.0,
                "total_tokens": 0,
                "elapsed_seconds": 0.0
            }

        self.logger.info(f"Processing {len(requests)} OCR requests...")
        start_time = time.time()

        # Stats tracking (thread-safe via lock)
        stats_lock = __import__('threading').Lock()
        stats = {
            "completed": 0,
            "failed": 0,
            "total_cost_usd": 0.0,
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_execution_time": 0.0  # Sum of individual request times
        }

        # Track recent completions (last 5) for display
        recent_completions = []  # List of request IDs in completion order

        # Create hierarchical progress bar (thread-safe for concurrent updates)
        progress = RichProgressBarHierarchical(
            total=len(requests),
            prefix="   ",
            width=40,
            unit="pages"
        ) if self.verbose else None

        if progress:
            progress.update(0, suffix="starting OCR...")

        completed_count = 0

        def process_single_request(request: OCRRequest) -> OCRResult:
            """Process a single OCR request."""
            nonlocal completed_count
            req_start = time.time()

            try:
                # Make OCR call
                text, usage, cost = self.ocr_provider.extract_text(
                    image=request.image,
                    prompt=request.prompt
                )

                req_time = time.time() - req_start
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)

                # Update stats
                with stats_lock:
                    stats["completed"] += 1
                    stats["total_cost_usd"] += cost
                    stats["total_prompt_tokens"] += prompt_tokens
                    stats["total_completion_tokens"] += completion_tokens
                    stats["total_execution_time"] += req_time
                    completed_count = stats["completed"]

                # Update progress bar (thread-safe)
                if progress:
                    cost_cents = cost * 100
                    page_num = request.metadata.get('page_num', request.id)
                    page_id = f"p{page_num}" if isinstance(page_num, int) else str(page_num)

                    # Add detailed line for this page
                    msg = f"{page_id}: [bold green]✓[/bold green] [dim]({req_time:.1f}s, {prompt_tokens}→{completion_tokens} tok, {cost_cents:.2f}¢)[/dim]"

                    with stats_lock:
                        progress.add_sub_line(request.id, msg)
                        # Track recent completions (keep last 5)
                        recent_completions.append(request.id)
                        if len(recent_completions) > 5:
                            recent_completions.pop(0)

                        # Update rollup metrics
                        elapsed = time.time() - start_time
                        pages_per_sec = completed_count / elapsed if elapsed > 0 else 0
                        avg_cost_cents = (stats['total_cost_usd'] / completed_count * 100) if completed_count > 0 else 0
                        avg_time = stats['total_execution_time'] / completed_count if completed_count > 0 else 0
                        avg_input = stats['total_prompt_tokens'] / completed_count if completed_count > 0 else 0
                        avg_output = stats['total_completion_tokens'] / completed_count if completed_count > 0 else 0

                        rollup_ids = []
                        if pages_per_sec > 0:
                            progress.add_sub_line("rollup_throughput",
                                f"[cyan]Throughput:[/cyan] [bold]{pages_per_sec:.1f}[/bold] [dim]pages/sec[/dim]")
                            rollup_ids.append("rollup_throughput")

                        if avg_cost_cents > 0:
                            progress.add_sub_line("rollup_avg_cost",
                                f"[cyan]Avg cost:[/cyan] [bold yellow]{avg_cost_cents:.2f}¢[/bold yellow][dim]/page[/dim]")
                            rollup_ids.append("rollup_avg_cost")

                        if avg_time > 0:
                            progress.add_sub_line("rollup_avg_time",
                                f"[cyan]Avg time:[/cyan] [bold]{avg_time:.1f}s[/bold][dim]/page[/dim]")
                            rollup_ids.append("rollup_avg_time")

                        if avg_input > 0:
                            progress.add_sub_line("rollup_tokens",
                                f"[cyan]Tokens:[/cyan] [green]{avg_input:.0f}[/green] in → [blue]{avg_output:.0f}[/blue] out")
                            rollup_ids.append("rollup_tokens")

                        # Set sections (rollups first, then recent)
                        if rollup_ids:
                            progress.set_section("rollups", "Metrics:", rollup_ids)
                        progress.set_section("recent", f"Recent ({len(recent_completions)}):", recent_completions[:])

                    # Update summary suffix (matches LLM batch processor format)
                    elapsed_mins = int(elapsed // 60)
                    elapsed_secs = int(elapsed % 60)
                    elapsed_str = f"{elapsed_mins}:{elapsed_secs:02d}"

                    # Calculate ETA
                    remaining = len(requests) - completed_count
                    if pages_per_sec > 0 and remaining > 0:
                        eta_seconds = remaining / pages_per_sec
                        eta_mins = int(eta_seconds // 60)
                        eta_secs = int(eta_seconds % 60)
                        eta_str = f"ETA {eta_mins}:{eta_secs:02d}"
                        suffix = f"{completed_count}/{len(requests)} • {elapsed_str} • {eta_str} • ${stats['total_cost_usd']:.2f}"
                    else:
                        suffix = f"{completed_count}/{len(requests)} • {elapsed_str} • ${stats['total_cost_usd']:.2f}"

                    progress.update(completed_count, suffix=suffix)

                return OCRResult(
                    request_id=request.id,
                    success=True,
                    text=text,
                    execution_time_seconds=req_time,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost_usd=cost,
                    request=request
                )

            except Exception as e:
                req_time = time.time() - req_start

                with stats_lock:
                    stats["failed"] += 1
                    stats["total_execution_time"] += req_time
                    completed_count = stats["completed"] + stats["failed"]

                if progress:
                    page_num = request.metadata.get('page_num', request.id)
                    page_id = f"p{page_num}" if isinstance(page_num, int) else str(page_num)

                    # Add detailed line for this page
                    error_msg = str(e)[:30]
                    msg = f"{page_id}: [bold red]✗[/bold red] [dim]({req_time:.1f}s)[/dim] - [yellow]{error_msg}[/yellow]"

                    with stats_lock:
                        progress.add_sub_line(request.id, msg)
                        # Track recent completions (keep last 5)
                        recent_completions.append(request.id)
                        if len(recent_completions) > 5:
                            recent_completions.pop(0)

                        # Update rollup metrics
                        elapsed = time.time() - start_time
                        total_processed = stats['completed'] + stats['failed']
                        pages_per_sec = total_processed / elapsed if elapsed > 0 else 0
                        avg_cost_cents = (stats['total_cost_usd'] / stats['completed'] * 100) if stats['completed'] > 0 else 0
                        avg_time = stats['total_execution_time'] / total_processed if total_processed > 0 else 0
                        avg_input = stats['total_prompt_tokens'] / stats['completed'] if stats['completed'] > 0 else 0
                        avg_output = stats['total_completion_tokens'] / stats['completed'] if stats['completed'] > 0 else 0

                        rollup_ids = []
                        if pages_per_sec > 0:
                            progress.add_sub_line("rollup_throughput",
                                f"[cyan]Throughput:[/cyan] [bold]{pages_per_sec:.1f}[/bold] [dim]pages/sec[/dim]")
                            rollup_ids.append("rollup_throughput")

                        if avg_cost_cents > 0:
                            progress.add_sub_line("rollup_avg_cost",
                                f"[cyan]Avg cost:[/cyan] [bold yellow]{avg_cost_cents:.2f}¢[/bold yellow][dim]/page[/dim]")
                            rollup_ids.append("rollup_avg_cost")

                        if avg_time > 0:
                            progress.add_sub_line("rollup_avg_time",
                                f"[cyan]Avg time:[/cyan] [bold]{avg_time:.1f}s[/bold][dim]/page[/dim]")
                            rollup_ids.append("rollup_avg_time")

                        if avg_input > 0:
                            progress.add_sub_line("rollup_tokens",
                                f"[cyan]Tokens:[/cyan] [green]{avg_input:.0f}[/green] in → [blue]{avg_output:.0f}[/blue] out")
                            rollup_ids.append("rollup_tokens")

                        # Set sections (rollups first, then recent)
                        if rollup_ids:
                            progress.set_section("rollups", "Metrics:", rollup_ids)
                        progress.set_section("recent", f"Recent ({len(recent_completions)}):", recent_completions[:])

                    # Update summary suffix (matches LLM batch processor format)
                    elapsed_mins = int(elapsed // 60)
                    elapsed_secs = int(elapsed % 60)
                    elapsed_str = f"{elapsed_mins}:{elapsed_secs:02d}"

                    # Calculate ETA
                    remaining = len(requests) - completed_count
                    if pages_per_sec > 0 and remaining > 0:
                        eta_seconds = remaining / pages_per_sec
                        eta_mins = int(eta_seconds // 60)
                        eta_secs = int(eta_seconds % 60)
                        eta_str = f"ETA {eta_mins}:{eta_secs:02d}"
                        suffix = f"{stats['completed']}/{len(requests)} • {elapsed_str} • {eta_str} • ${stats['total_cost_usd']:.2f}"
                    else:
                        suffix = f"{stats['completed']}/{len(requests)} • {elapsed_str} • ${stats['total_cost_usd']:.2f}"

                    progress.update(completed_count, suffix=suffix)

                return OCRResult(
                    request_id=request.id,
                    success=False,
                    error_message=str(e),
                    execution_time_seconds=req_time,
                    request=request
                )

        # Process requests in parallel
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(process_single_request, req): req for req in requests}

            for future in as_completed(futures):
                result = future.result()
                on_result(result)

        # Finish progress bar
        elapsed = time.time() - start_time

        if progress:
            summary_text = format_batch_summary(
                batch_name=self.batch_name,
                completed=stats['completed'],
                total=len(requests),
                time_seconds=elapsed,
                prompt_tokens=stats['total_prompt_tokens'],
                completion_tokens=stats['total_completion_tokens'],
                reasoning_tokens=0,  # OlmOCR doesn't use reasoning tokens
                cost_usd=stats['total_cost_usd'],
                unit="pages"
            )
            # RichProgressBarHierarchical.finish() needs a string, so convert
            from rich.console import Console
            console = Console()
            with console.capture() as capture:
                console.print(summary_text)
            progress.finish(capture.get().rstrip())

        self.logger.info(
            f"{self.batch_name} batch complete: {stats['completed']} completed, "
            f"{stats['failed']} failed, "
            f"${stats['total_cost_usd']:.4f}, "
            f"{stats['total_prompt_tokens'] + stats['total_completion_tokens']} tokens"
        )

        return {
            "completed": stats["completed"],
            "failed": stats["failed"],
            "total_cost_usd": stats["total_cost_usd"],
            "total_tokens": stats["total_prompt_tokens"] + stats["total_completion_tokens"],
            "elapsed_seconds": elapsed
        }
