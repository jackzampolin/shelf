import time
from datetime import datetime
from typing import List
from concurrent.futures import ThreadPoolExecutor, as_completed

from infra.storage.book_storage import BookStorage
from infra.storage.checkpoint import CheckpointManager
from infra.pipeline.logger import PipelineLogger
from infra.llm.batch_processor import LLMBatchProcessor
from infra.llm.batch_client import LLMRequest, LLMResult
from infra.llm.metrics import llm_result_to_metrics

from ..vision import prepare_correction_request
from ..schemas import ParagraphCorrectPageOutput, ParagraphCorrectPageMetrics
from .quality_metrics import calculate_similarity_metrics


def correct_pages(
    storage: BookStorage,
    checkpoint: CheckpointManager,
    logger: PipelineLogger,
    stage_storage,
    model: str,
    max_workers: int,
    max_retries: int,
    remaining_pages: List[int],
    total_pages: int,
    output_schema,
):
    if not remaining_pages:
        logger.info("No pages to correct")
        return

    logger.info(f"Correcting {len(remaining_pages)} pages with {model}")
    start_time = time.time()

    logger.info(f"Loading {len(remaining_pages)} pages...")
    load_start = time.time()

    requests = []
    page_data_map = {}

    def load_page(page_num):
        try:
            request, ocr_page = prepare_correction_request(
                page_num=page_num,
                storage=storage,
                model=model,
                total_pages=total_pages,
            )
            return (page_num, request, ocr_page)
        except Exception as e:
            logger.error(f"Failed to prepare page {page_num}", error=str(e))
            return None

    from infra.pipeline.rich_progress import RichProgressBarHierarchical
    load_progress = RichProgressBarHierarchical(
        total=len(remaining_pages),
        prefix="   ",
        width=40,
        unit="pages"
    )
    load_progress.update(0, suffix="loading OCR data...")

    loaded = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_page = {
            executor.submit(load_page, page_num): page_num
            for page_num in remaining_pages
        }

        for future in as_completed(future_to_page):
            result = future.result()
            if result:
                page_num, request, ocr_page = result
                requests.append(request)
                page_data_map[page_num] = ocr_page

            loaded += 1
            load_progress.update(loaded, suffix=f"{loaded}/{len(remaining_pages)} pages loaded")

    load_elapsed = time.time() - load_start
    load_progress.finish(f"   ✓ Loaded {len(requests)} pages in {load_elapsed:.1f}s")

    if not requests:
        logger.warning("No valid requests to process")
        return

    stage_log_dir = storage.stage("paragraph_correct").output_dir / "logs"
    processor = LLMBatchProcessor(
        checkpoint=checkpoint,
        logger=logger,
        model=model,
        log_dir=stage_log_dir,
        max_workers=max_workers,
        max_retries=max_retries,
        verbose=True,
    )

    failed_pages = []

    def on_result(result: LLMResult):
        page_num = result.request.metadata['page_num']
        ocr_page = page_data_map[page_num]

        if not result.success:
            logger.error(f"Page {page_num} failed", error=result.error)
            failed_pages.append(page_num)
            return

        try:
            correction_data = result.parsed_json
            if correction_data is None:
                raise ValueError("parsed_json is None for successful result")

            similarity_ratio, chars_changed = calculate_similarity_metrics(
                ocr_page=ocr_page,
                correction_data=correction_data
            )

            page_output = {
                'page_number': page_num,
                'blocks': correction_data['blocks'],
                'model_used': model,
                'processing_cost': result.cost_usd,
                'timestamp': datetime.now().isoformat(),
                'total_blocks': len(correction_data['blocks']),
                'total_corrections': sum(
                    1 for block in correction_data['blocks']
                    for para in block['paragraphs']
                    if para.get('text') is not None
                ),
                'avg_confidence': sum(
                    para['confidence']
                    for block in correction_data['blocks']
                    for para in block['paragraphs']
                ) / max(1, sum(
                    len(block['paragraphs'])
                    for block in correction_data['blocks']
                ))
            }

            validated = output_schema(**page_output)

            metrics = ParagraphCorrectPageMetrics(**llm_result_to_metrics(
                result=result,
                page_num=page_num,
                extra_fields={
                    "total_corrections": page_output['total_corrections'],
                    "avg_confidence": page_output['avg_confidence'],
                    "text_similarity_ratio": similarity_ratio,
                    "characters_changed": chars_changed,
                }
            ))

            stage_storage.save_corrected_page(
                storage=storage,
                page_num=page_num,
                data=validated.model_dump(),
                schema=output_schema,
                cost_usd=result.cost_usd,
                metrics=metrics.model_dump()
            )

        except Exception as e:
            logger.error(f"Failed to save page {page_num}", error=str(e))
            failed_pages.append(page_num)

    batch_stats = processor.process_batch(
        requests=requests,
        on_result=on_result,
    )

    elapsed = time.time() - start_time
    logger.info(
        f"Correction complete: {batch_stats['completed']} succeeded, "
        f"{batch_stats['failed']} failed, "
        f"${batch_stats['total_cost_usd']:.4f} in {elapsed:.1f}s"
    )

    if failed_pages:
        logger.warning(f"Failed pages: {sorted(failed_pages)[:10]}")
