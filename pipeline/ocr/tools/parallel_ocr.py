import threading
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import List

from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.pipeline.rich_progress import RichProgressBar

from ..providers import OCRProvider, TesseractProvider
from .worker import process_ocr_task
from ..storage import OCRStageStorage


def run_parallel_ocr(
    storage: BookStorage,
    logger: PipelineLogger,
    ocr_storage: OCRStageStorage,
    providers: List[OCRProvider],
    output_schema,  # OCRPageOutput schema
    total_pages: int,
    max_workers: int,
    stage_name: str,
):
    # Build task list by checking file existence (ground truth from disk)
    tasks = []
    for page_num in range(1, total_pages + 1):
        for provider_idx, provider in enumerate(providers):
            # Check if provider output already exists on disk
            if not ocr_storage.provider_page_exists(storage, provider.config.name, page_num):
                tasks.append((page_num, provider_idx))

    if not tasks:
        logger.info("No OCR tasks remaining (all providers complete)")
        return

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

    worker_tasks = []
    for page_num, provider_idx in tasks:
        provider = providers[provider_idx]
        source_file = storage.stage("source").output_page(page_num, extension="png")

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

        if isinstance(provider, TesseractProvider):
            worker_task["provider_kwargs"] = {
                "psm_mode": provider.psm_mode,
                "use_opencl": provider.use_opencl,
            }

        worker_tasks.append(worker_task)

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
                    # Save provider output (file on disk = ground truth)
                    ocr_storage.save_provider_output(
                        storage, page_num, provider_name, result, output_schema
                    )
                    # Note: No metrics needed - provider completion is derivable from file existence

                with lock:
                    completed += 1
                    progress.update(completed, suffix=f"{completed}/{len(tasks)}")

            except Exception as e:
                logger.error(f"Error processing future result: {e}")
                import traceback
                traceback.print_exc()

    progress.finish(f"   ✓ {completed}/{len(tasks)} OCR tasks complete")
