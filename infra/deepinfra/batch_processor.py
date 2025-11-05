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
            "total_completion_tokens": 0
        }

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
                    completed_count = stats["completed"]

                # Update progress bar (thread-safe)
                if progress:
                    cost_cents = cost * 100
                    page_info = request.metadata.get('page_num', request.id)
                    suffix = f"page {page_info} ({req_time:.1f}s, {cost_cents:.2f}¢)"
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
                    completed_count = stats["completed"] + stats["failed"]

                if progress:
                    page_info = request.metadata.get('page_num', request.id)
                    suffix = f"page {page_info} FAILED"
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
