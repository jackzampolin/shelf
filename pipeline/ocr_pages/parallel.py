"""
Parallel OCR processor.

Runs multiple OCR providers concurrently using the existing OCRBatchProcessor.

Architecture:
- Each provider runs its full batch in parallel with other providers
- Reuses existing OCRBatchProcessor infrastructure (rate limiting, progress, retries)
- Unified progress display polls disk state for all providers
"""

import time
import threading
from typing import Dict, List, Any
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn, TaskProgressColumn

from infra.ocr import OCRProvider, OCRBatchProcessor, OCRBatchConfig
from infra.pipeline.status import PhaseStatusTracker
from infra.llm.display import is_headless


def _get_provider_subdir(provider: OCRProvider) -> str:
    """Get subdirectory name for provider outputs."""
    name = provider.name
    for suffix in ["-ocr", "_ocr"]:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    return name.replace("-", "_")


def _create_provider_tracker(
    stage_storage,
    provider: OCRProvider,
) -> PhaseStatusTracker:
    """Create a PhaseStatusTracker for a single OCR provider."""
    subdir = _get_provider_subdir(provider)
    source_storage = stage_storage.storage.stage("source")
    source_pages = source_storage.list_pages(extension="png")

    return PhaseStatusTracker(
        stage_storage=stage_storage,
        phase_name=subdir,  # e.g., "mistral", "paddle"
        discoverer=lambda phase_dir: source_pages,
        output_path_fn=lambda page_num, phase_dir: phase_dir / f"page_{page_num:04d}.json",
        run_fn=lambda tracker, **kwargs: {},  # Not used - we call OCRBatchProcessor directly
        use_subdir=True,  # Creates output in e.g., ocr-pages/mistral/
        description=f"OCR using {provider.name}",
    )


def _count_provider_pages(stage_storage, provider: OCRProvider) -> int:
    """Count completed pages for a provider by checking disk."""
    subdir = _get_provider_subdir(provider)
    provider_dir = stage_storage.output_dir / subdir
    if not provider_dir.exists():
        return 0
    return len(list(provider_dir.glob("page_*.json")))


def _get_provider_cost(stage_storage, provider: OCRProvider) -> float:
    """Get total cost for a provider from metrics."""
    subdir = _get_provider_subdir(provider)
    prefix = f"ocr_{subdir}_"
    metrics = stage_storage.metrics_manager.get_cumulative_metrics(prefix=prefix)
    return metrics.get("total_cost_usd", 0.0)


def run_providers_parallel(
    stage_storage,
    providers: List[OCRProvider],
    max_workers_per_provider: int = 10,
) -> Dict[str, Any]:
    """
    Run all OCR providers in parallel.

    Each provider processes all pages using OCRBatchProcessor.
    All providers run concurrently with unified progress display.
    """
    logger = stage_storage.logger()
    results = {}
    results_lock = threading.Lock()

    # Get total pages
    source_storage = stage_storage.storage.stage("source")
    total_pages = len(source_storage.list_pages(extension="png"))

    def run_single_provider(provider: OCRProvider) -> Dict[str, Any]:
        """Run a single provider's batch."""
        subdir = _get_provider_subdir(provider)
        tracker = _create_provider_tracker(stage_storage, provider)

        # Check if already complete
        if tracker.is_completed():
            return {"provider": provider.name, "status": "skipped"}

        # Use the metrics prefix that matches the phase: ocr_{subdir}_
        tracker.metrics_prefix = f"ocr_{subdir}_"

        config = OCRBatchConfig(
            tracker=tracker,
            provider=provider,
            batch_name=provider.name,
            max_workers=max_workers_per_provider,
            silent=True,  # We handle display ourselves
        )

        result = OCRBatchProcessor(config).process_batch()
        return {"provider": provider.name, **result}

    logger.info(f"Running {len(providers)} OCR providers in parallel...")
    start_time = time.time()

    # Flag to stop the display thread
    processing_done = threading.Event()

    # Create progress display with standard format - one task per provider
    progress = Progress(
        TextColumn("⏳ {task.description}"),
        BarColumn(bar_width=40),
        TaskProgressColumn(),
        TextColumn("{task.fields[suffix]}", justify="right"),
        transient=True,
        disable=is_headless(),
    )

    # Create tasks for each provider
    task_ids = {}
    for provider in providers:
        short_name = provider.name.replace("-ocr", "").replace("_ocr", "")
        task_id = progress.add_task(short_name, total=total_pages, suffix="starting...")
        task_ids[provider.name] = task_id

    def update_progress():
        """Background thread to poll disk and update progress."""
        while not processing_done.is_set():
            for provider in providers:
                completed = _count_provider_pages(stage_storage, provider)
                cost = _get_provider_cost(stage_storage, provider)
                suffix = f"{completed}/{total_pages} • ${cost:.2f}"
                progress.update(task_ids[provider.name], completed=completed, suffix=suffix)
            time.sleep(1)
        # Final update
        for provider in providers:
            completed = _count_provider_pages(stage_storage, provider)
            cost = _get_provider_cost(stage_storage, provider)
            suffix = f"{completed}/{total_pages} • ${cost:.2f}"
            progress.update(task_ids[provider.name], completed=completed, suffix=suffix)

    # Start progress and update thread
    progress.start()
    update_thread = threading.Thread(target=update_progress, daemon=True)
    update_thread.start()

    # Run all providers in parallel
    with ThreadPoolExecutor(max_workers=len(providers)) as executor:
        futures = {
            executor.submit(run_single_provider, provider): provider.name
            for provider in providers
        }

        for future in as_completed(futures):
            provider_name = futures[future]
            try:
                result = future.result()
                with results_lock:
                    results[provider_name] = result
            except Exception as e:
                logger.error(f"{provider_name} failed: {e}")
                with results_lock:
                    results[provider_name] = {"provider": provider_name, "status": "failed", "error": str(e)}

    # Stop display
    processing_done.set()
    update_thread.join(timeout=2)
    progress.stop()

    # Print completion summary using standard format
    from infra.llm.display import DisplayStats, print_ocr_complete
    elapsed = time.time() - start_time

    for provider in providers:
        short_name = provider.name.replace("-ocr", "").replace("_ocr", "")
        completed = _count_provider_pages(stage_storage, provider)
        cost = _get_provider_cost(stage_storage, provider)
        print_ocr_complete(short_name, DisplayStats(
            completed=completed,
            total=total_pages,
            time_seconds=elapsed,
            cost_usd=cost,
        ))

    # Aggregate results
    total_cost = sum(_get_provider_cost(stage_storage, p) for p in providers)
    total_completed = sum(_count_provider_pages(stage_storage, p) for p in providers)
    all_success = all(r.get("status") in ("success", "skipped") for r in results.values())

    return {
        "status": "success" if all_success else "partial",
        "providers": results,
        "total_pages_processed": total_completed,
        "total_cost": total_cost,
    }


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
        max_workers: Max concurrent pages per provider

    Returns:
        PhaseStatusTracker configured for parallel OCR
    """
    source_storage = stage_storage.storage.stage("source")
    source_pages = source_storage.list_pages(extension="png")

    # Get provider subdirectory names for validation
    provider_subdirs = [_get_provider_subdir(p) for p in providers]

    def validator(page_num: int, phase_dir: Path) -> bool:
        """Check if ALL providers have output for this page."""
        for subdir in provider_subdirs:
            output_file = phase_dir / subdir / f"page_{page_num:04d}.json"
            if not output_file.exists():
                return False
        return True

    def run_parallel_ocr(tracker: PhaseStatusTracker, **kwargs) -> Dict[str, Any]:
        """Run all providers in parallel."""
        return run_providers_parallel(
            stage_storage=stage_storage,
            providers=providers,
            max_workers_per_provider=max_workers,
        )

    return PhaseStatusTracker(
        stage_storage=stage_storage,
        phase_name="ocr",
        discoverer=lambda phase_dir: source_pages,
        output_path_fn=lambda page_num, phase_dir: phase_dir / f"page_{page_num:04d}.json",
        run_fn=run_parallel_ocr,
        use_subdir=False,  # Output goes to provider subdirs
        validator_override=validator,
        description="Extract text using multiple OCR providers in parallel",
    )
