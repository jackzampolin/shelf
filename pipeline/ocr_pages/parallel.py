"""
Parallel OCR processor.

Runs multiple OCR providers concurrently for each page, then moves to blend.

Architecture:
- Before: mistral (all pages) → paddle (all pages) → olmocr (all pages) → blend
- After:  [mistral + paddle + olmocr] per page → blend

Progress display:
    ⏳ OCR Pages [████████░░░░] 80/100 pages
      mistral: 82/100  paddle: 80/100  olmocr: 78/100
      $0.1234 • 45.2s elapsed
"""

import time
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from PIL import Image
from pathlib import Path

from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.text import Text
from rich.progress import Progress, BarColumn, TextColumn, TaskProgressColumn

from infra.ocr import OCRProvider, OCRResult
from infra.llm.rate_limiter import RateLimiter
from infra.llm.display import is_headless
from infra.pipeline.status import PhaseStatusTracker


@dataclass
class ProviderStats:
    """Track stats for a single provider."""
    name: str
    completed: int = 0
    failed: int = 0
    total_cost: float = 0.0
    total_time: float = 0.0
    total_chars: int = 0
    rate_limit: Optional[float] = None


@dataclass
class ParallelOCRConfig:
    """Configuration for parallel OCR processing."""
    providers: List[OCRProvider]
    source_storage: Any  # StageStorage for source images
    stage_storage: Any   # StageStorage for OCR outputs
    max_workers: int = 10
    # Page numbers to process (if None, detect from source)
    page_nums: Optional[List[int]] = None


class ParallelOCRProcessor:
    """
    Run multiple OCR providers in parallel.

    For each page:
    1. Load image once
    2. Submit to all providers concurrently
    3. Each provider respects its own rate limit
    4. Save results per provider subdirectory

    Resume support: Only processes pages where at least one provider is missing.
    """

    def __init__(self, config: ParallelOCRConfig):
        self.config = config
        self.providers = config.providers
        self.source_storage = config.source_storage
        self.stage_storage = config.stage_storage
        self.max_workers = config.max_workers

        # Create per-provider rate limiters
        self.rate_limiters: Dict[str, Optional[RateLimiter]] = {}
        for provider in self.providers:
            if provider.requests_per_second != float('inf'):
                rpm = int(provider.requests_per_second * 60)
                self.rate_limiters[provider.name] = RateLimiter(requests_per_minute=rpm)
            else:
                self.rate_limiters[provider.name] = None

        # Stats tracking
        self.stats: Dict[str, ProviderStats] = {
            p.name: ProviderStats(
                name=p.name,
                rate_limit=p.requests_per_second if p.requests_per_second != float('inf') else None
            )
            for p in self.providers
        }
        self.stats_lock = threading.Lock()

        # Overall tracking
        self.pages_completed = 0  # Pages where ALL providers finished
        self.start_time = 0.0

    def get_page_nums(self) -> List[int]:
        """Get page numbers to process from source storage."""
        if self.config.page_nums is not None:
            return self.config.page_nums

        source_dir = self.source_storage.output_dir
        page_files = sorted(source_dir.glob("page_*.png"))
        return [int(f.stem.split("_")[1]) for f in page_files]

    def get_remaining_pages(self) -> List[int]:
        """
        Get pages that need processing.

        A page needs processing if ANY provider is missing output for it.
        """
        all_pages = self.get_page_nums()
        remaining = []

        for page_num in all_pages:
            needs_processing = False
            for provider in self.providers:
                # Check if this provider has output for this page
                output_file = (
                    self.stage_storage.output_dir /
                    provider.name.replace("-", "_") /
                    f"page_{page_num:04d}.json"
                )
                if not output_file.exists():
                    needs_processing = True
                    break

            if needs_processing:
                remaining.append(page_num)

        return remaining

    def _get_provider_subdir(self, provider: OCRProvider) -> str:
        """Get subdirectory name for provider outputs."""
        # Convert provider name to valid directory name
        # e.g., "mistral-ocr" -> "mistral", "paddle-ocr" -> "paddle"
        name = provider.name
        for suffix in ["-ocr", "_ocr"]:
            if name.endswith(suffix):
                name = name[:-len(suffix)]
        return name.replace("-", "_")

    def _process_page_with_provider(
        self,
        page_num: int,
        image: Image.Image,
        provider: OCRProvider,
    ) -> Dict[str, Any]:
        """Process a single page with a single provider."""
        provider_name = provider.name
        subdir = self._get_provider_subdir(provider)

        # Check if already processed
        output_file = self.stage_storage.output_dir / subdir / f"page_{page_num:04d}.json"
        if output_file.exists():
            return {
                "success": True,
                "provider": provider_name,
                "page_num": page_num,
                "skipped": True,
            }

        # Rate limit
        rate_limiter = self.rate_limiters.get(provider_name)
        if rate_limiter:
            rate_limiter.consume()

        # Process with retries
        result = None
        for attempt in range(provider.max_retries + 1):
            try:
                result = provider.process_image(image, page_num)

                if result.success:
                    result.retry_count = attempt
                    break
                else:
                    if attempt < provider.max_retries:
                        delay = provider.retry_delay_base ** attempt
                        time.sleep(delay)
                        continue
                    else:
                        return {
                            "success": False,
                            "provider": provider_name,
                            "page_num": page_num,
                            "error": result.error_message,
                        }
            except Exception as e:
                if attempt < provider.max_retries:
                    delay = provider.retry_delay_base ** attempt
                    time.sleep(delay)
                    continue
                else:
                    return {
                        "success": False,
                        "provider": provider_name,
                        "page_num": page_num,
                        "error": str(e),
                    }

        if result and result.success:
            # Save result
            provider.handle_result(
                page_num,
                result,
                subdir=subdir,
                metrics_prefix=f"{subdir}_"
            )

            # Update stats
            with self.stats_lock:
                stats = self.stats[provider_name]
                stats.completed += 1
                stats.total_cost += result.cost_usd
                stats.total_time += result.execution_time_seconds
                stats.total_chars += len(result.text)

            return {
                "success": True,
                "provider": provider_name,
                "page_num": page_num,
                "cost": result.cost_usd,
                "chars": len(result.text),
                "time": result.execution_time_seconds,
            }

        return {
            "success": False,
            "provider": provider_name,
            "page_num": page_num,
            "error": "Unknown error",
        }

    def _process_page_all_providers(
        self,
        page_num: int,
        image: Image.Image,
    ) -> Dict[str, Any]:
        """Process a single page with ALL providers in parallel."""
        results = {}

        # Submit to all providers concurrently
        with ThreadPoolExecutor(max_workers=len(self.providers)) as executor:
            futures = {
                executor.submit(
                    self._process_page_with_provider,
                    page_num,
                    image,
                    provider
                ): provider.name
                for provider in self.providers
            }

            for future in as_completed(futures):
                provider_name = futures[future]
                try:
                    result = future.result()
                    results[provider_name] = result
                except Exception as e:
                    results[provider_name] = {
                        "success": False,
                        "provider": provider_name,
                        "page_num": page_num,
                        "error": str(e),
                    }

        # Check if all providers succeeded
        all_success = all(r.get("success", False) for r in results.values())

        return {
            "page_num": page_num,
            "all_success": all_success,
            "results": results,
        }

    def _build_progress_display(self, total_pages: int, completed_pages: int) -> Table:
        """Build rich table for progress display."""
        elapsed = time.time() - self.start_time
        total_cost = sum(s.total_cost for s in self.stats.values())

        table = Table.grid(padding=(0, 2))
        table.add_column()

        # Main progress line
        pct = (completed_pages / total_pages * 100) if total_pages > 0 else 0
        bar_width = 40
        filled = int(bar_width * completed_pages / total_pages) if total_pages > 0 else 0
        bar = "█" * filled + "░" * (bar_width - filled)

        main_line = Text()
        main_line.append("⏳ OCR Pages ", style="bold")
        main_line.append(f"[{bar}] ", style="cyan")
        main_line.append(f"{completed_pages}/{total_pages} pages", style="")
        table.add_row(main_line)

        # Provider status line
        provider_line = Text("  ")
        for i, (name, stats) in enumerate(self.stats.items()):
            if i > 0:
                provider_line.append("  ")

            # Short name (first part before dash)
            short_name = name.split("-")[0][:8]

            if stats.completed == total_pages:
                provider_line.append(f"{short_name}: ", style="green")
                provider_line.append(f"{stats.completed}✓", style="green")
            else:
                provider_line.append(f"{short_name}: ", style="")
                provider_line.append(f"{stats.completed}/{total_pages}", style="yellow")

        table.add_row(provider_line)

        # Stats line
        stats_line = Text("  ")
        stats_line.append(f"${total_cost:.4f}", style="yellow")
        stats_line.append(" • ", style="dim")
        stats_line.append(f"{elapsed:.1f}s elapsed", style="dim")

        if completed_pages > 0:
            avg_time = elapsed / completed_pages
            stats_line.append(" • ", style="dim")
            stats_line.append(f"{avg_time:.2f}s/page", style="dim")

        table.add_row(stats_line)

        return table

    def process_batch(self) -> Dict[str, Any]:
        """
        Process all pages with all providers in parallel.

        Returns summary statistics.
        """
        page_nums = self.get_remaining_pages()
        total_pages = len(self.get_page_nums())

        if not page_nums:
            return {
                "status": "skipped",
                "reason": "all pages already processed",
                "total_pages": total_pages,
            }

        self.start_time = time.time()
        source_dir = self.source_storage.output_dir

        # Track pages where all providers succeeded
        completed_pages = 0
        failed_pages = []

        # Initialize completed count from already-done pages
        already_done = total_pages - len(page_nums)
        completed_pages = already_done

        # Also initialize provider stats for already-done pages
        for provider in self.providers:
            subdir = self._get_provider_subdir(provider)
            existing = list((self.stage_storage.output_dir / subdir).glob("page_*.json"))
            self.stats[provider.name].completed = len(existing)

        console = Console()
        headless = is_headless()

        def process_single_page(page_num: int) -> Dict[str, Any]:
            """Load image and process with all providers."""
            page_file = source_dir / f"page_{page_num:04d}.png"

            if not page_file.exists():
                return {
                    "page_num": page_num,
                    "all_success": False,
                    "error": f"Source image not found: {page_file}",
                }

            try:
                image = Image.open(page_file)
            except Exception as e:
                return {
                    "page_num": page_num,
                    "all_success": False,
                    "error": f"Failed to load image: {e}",
                }

            return self._process_page_all_providers(page_num, image)

        if headless:
            # Simple output for headless mode
            console.print(f"Processing {len(page_nums)} pages with {len(self.providers)} providers...")

            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {
                    executor.submit(process_single_page, page_num): page_num
                    for page_num in page_nums
                }

                for future in as_completed(futures):
                    result = future.result()
                    if result.get("all_success"):
                        completed_pages += 1
                    else:
                        failed_pages.append(result["page_num"])
        else:
            # Rich live display
            with Live(
                self._build_progress_display(total_pages, completed_pages),
                console=console,
                refresh_per_second=4,
                transient=True,
            ) as live:
                with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    futures = {
                        executor.submit(process_single_page, page_num): page_num
                        for page_num in page_nums
                    }

                    for future in as_completed(futures):
                        result = future.result()
                        if result.get("all_success"):
                            completed_pages += 1
                        else:
                            failed_pages.append(result["page_num"])

                        live.update(self._build_progress_display(total_pages, completed_pages))

        # Print completion summary
        elapsed = time.time() - self.start_time
        total_cost = sum(s.total_cost for s in self.stats.values())
        total_chars = sum(s.total_chars for s in self.stats.values())

        self._print_completion_summary(total_pages, completed_pages, elapsed, total_cost, total_chars)

        # Determine status
        if completed_pages == total_pages:
            status = "success"
        elif completed_pages > 0:
            status = "partial"
        else:
            status = "failed"

        return {
            "status": status,
            "pages_processed": completed_pages,
            "pages_failed": len(failed_pages),
            "failed_pages": failed_pages,
            "total_cost": total_cost,
            "total_chars": total_chars,
            "total_time": elapsed,
            "provider_stats": {
                name: {
                    "completed": s.completed,
                    "failed": s.failed,
                    "cost": s.total_cost,
                    "chars": s.total_chars,
                }
                for name, s in self.stats.items()
            },
        }

    def _print_completion_summary(
        self,
        total: int,
        completed: int,
        elapsed: float,
        cost: float,
        chars: int,
    ):
        """Print completion summary."""
        console = Console()

        text = Text()
        text.append("✅ ", style="green")
        text.append("OCR Pages: ", style="bold")
        text.append(f"{completed}/{total}", style="")
        text.append(f"  ({elapsed:.1f}s)", style="dim")
        text.append(f"  {chars:,} chars", style="cyan")
        text.append(f"  ${cost:.4f}", style="yellow")

        console.print(text)

        # Provider breakdown
        for name, stats in self.stats.items():
            short_name = name.split("-")[0]
            provider_text = Text()
            provider_text.append(f"  {short_name}: ", style="dim")
            provider_text.append(f"{stats.completed}/{total}", style="")
            provider_text.append(f" ${stats.total_cost:.4f}", style="yellow dim")
            console.print(provider_text)


def create_parallel_ocr_tracker(
    stage_storage,
    providers: List[OCRProvider],
    max_workers: int = 10,
) -> PhaseStatusTracker:
    """
    Create a PhaseStatusTracker for parallel OCR processing.

    Args:
        stage_storage: StageStorage instance
        providers: List of OCR providers to run in parallel
        max_workers: Max concurrent pages to process

    Returns:
        PhaseStatusTracker configured for parallel OCR
    """
    book_storage = stage_storage.storage
    source_storage = book_storage.stage("source")
    source_pages = source_storage.list_pages(extension="png")

    # Get provider subdirectory names
    provider_subdirs = []
    for p in providers:
        name = p.name
        for suffix in ["-ocr", "_ocr"]:
            if name.endswith(suffix):
                name = name[:-len(suffix)]
        provider_subdirs.append(name.replace("-", "_"))

    def validator(page_num: int, phase_dir: Path) -> bool:
        """Check if ALL providers have output for this page."""
        for subdir in provider_subdirs:
            output_file = phase_dir / subdir / f"page_{page_num:04d}.json"
            if not output_file.exists():
                return False
        return True

    def run_parallel_ocr(tracker: PhaseStatusTracker, **kwargs) -> Dict[str, Any]:
        """Run parallel OCR processing."""
        config = ParallelOCRConfig(
            providers=providers,
            source_storage=source_storage,
            stage_storage=stage_storage,
            max_workers=max_workers,
        )
        processor = ParallelOCRProcessor(config)
        return processor.process_batch()

    return PhaseStatusTracker(
        stage_storage=stage_storage,
        phase_name="ocr",
        discoverer=lambda phase_dir: source_pages,
        output_path_fn=lambda page_num, phase_dir: phase_dir / f"page_{page_num:04d}.json",  # Not used directly
        run_fn=run_parallel_ocr,
        use_subdir=False,  # Output goes to provider subdirs, not ocr subdir
        validator_override=validator,
        description="Extract text using multiple OCR providers in parallel",
    )
