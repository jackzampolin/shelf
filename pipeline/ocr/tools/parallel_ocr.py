"""
Parallel OCR orchestrator for OCR (Phase 1).

Executes all OCR providers in parallel using ProcessPoolExecutor,
with incremental checkpoint updates as each provider completes.
"""

import threading
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import List

from infra.storage.book_storage import BookStorage
from infra.storage.checkpoint import CheckpointManager
from infra.pipeline.logger import PipelineLogger
from infra.pipeline.rich_progress import RichProgressBar

from ..providers import OCRProvider, TesseractProvider
from .worker import process_ocr_task
from ..storage import OCRStageStorage
from ..status import OCRStageStatus


def run_parallel_ocr(
    storage: BookStorage,
    checkpoint: CheckpointManager,
    logger: PipelineLogger,
    ocr_storage: OCRStageStorage,
    providers: List[OCRProvider],
    output_schema,  # OCRPageOutput schema
    total_pages: int,
    max_workers: int,
    stage_name: str,
):
    """
    Run all OCR providers in parallel for pages that need them.

    Updates checkpoint incrementally as each provider completes.

    Args:
        storage: BookStorage instance
        checkpoint: CheckpointManager instance
        logger: PipelineLogger instance
        ocr_storage: OCRStageStorage instance
        providers: List of OCR providers
        output_schema: Pydantic schema for validation (OCRPageOutput)
        total_pages: Total pages in book
        max_workers: CPU workers for parallel processing
        stage_name: Stage name (for source file lookup)
    """
    # Build tasks: only (page, provider) pairs that haven't completed
    tasks = []
    for page_num in range(1, total_pages + 1):
        # Get page metrics from checkpoint
        page_metrics = checkpoint.get_page_metrics(page_num)
        providers_complete = page_metrics.get("providers_complete", []) if page_metrics else []

        # Add tasks for providers not yet complete
        for provider_idx, provider in enumerate(providers):
            if provider.config.name not in providers_complete:
                tasks.append((page_num, provider_idx))

    if not tasks:
        logger.info("No OCR tasks remaining (all providers complete)")
        return

    # Count unique pages in tasks
    unique_pages = len(set(page_num for page_num, _ in tasks))
    logger.info(f"Running {len(tasks)} OCR tasks ({unique_pages} pages × up to {len(providers)} providers)")

    progress = RichProgressBar(
        total=len(tasks),
        prefix="   ",
        width=40,
        unit="tasks",
    )
    progress.update(0, suffix="starting...")

    completed = 0
    lock = threading.Lock()

    # Build worker tasks (serializable for ProcessPoolExecutor)
    worker_tasks = []
    for page_num, provider_idx in tasks:
        provider = providers[provider_idx]
        source_file = storage.stage("source").output_page(page_num, extension="png")

        # Serialize provider config for worker
        worker_task = {
            "page_num": page_num,
            "source_file": str(source_file),
            "provider_config": {
                "name": provider.config.name,
                "enabled": provider.config.enabled,
                "cost_per_page": provider.config.cost_per_page,
                "metadata": provider.config.metadata,
            },
            "provider_class": provider.__class__.__name__,
            "provider_kwargs": {},
        }

        # Add provider-specific kwargs
        if isinstance(provider, TesseractProvider):
            worker_task["provider_kwargs"] = {
                "psm_mode": provider.psm_mode,
                "use_opencl": provider.use_opencl,
            }

        worker_tasks.append(worker_task)

    # Execute in parallel
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_task = {
            executor.submit(process_ocr_task, task): task for task in worker_tasks
        }

        for future in as_completed(future_to_task):
            try:
                page_num, provider_name, result, error = future.result()

                if error:
                    logger.page_error(f"OCR failed for {provider_name}", page=page_num, error=error)
                elif result is not None:
                    # Save provider output to disk
                    ocr_storage.save_provider_output(
                        storage, page_num, provider_name, result, output_schema
                    )

                    # ✓ Update checkpoint immediately
                    with lock:
                        page_metrics = checkpoint.get_page_metrics(page_num) or {}
                        providers_complete = list(page_metrics.get("providers_complete", []))  # Copy list

                        if provider_name not in providers_complete:
                            providers_complete.append(provider_name)

                            # Update checkpoint with new provider completion
                            checkpoint.update_page_metrics(page_num, {
                                "page_num": page_num,
                                "providers_complete": providers_complete,
                                "processing_time_seconds": page_metrics.get("processing_time_seconds", 0.0) + result.metadata.get("processing_time_seconds", 0.0),
                            })

                with lock:
                    completed += 1
                    progress.update(completed, suffix=f"{completed}/{len(tasks)}")

                    # Update phase details every 10 tasks for status visibility
                    if completed % 10 == 0 or completed == len(tasks):
                        checkpoint.set_phase(OCRStageStatus.RUNNING_OCR.value, f"{completed}/{len(tasks)} tasks")

            except Exception as e:
                logger.error(f"Error processing future result: {e}")
                import traceback
                traceback.print_exc()

    progress.finish(f"   ✓ {completed}/{len(tasks)} OCR tasks complete")
