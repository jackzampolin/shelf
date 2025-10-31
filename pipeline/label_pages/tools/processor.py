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

from ..vision import prepare_label_request, BlockType
from ..schemas import LabelPagesPageOutput, LabelPagesPageMetrics


def label_pages(
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
        logger.info("No pages to label")
        return

    logger.info(f"Labeling {len(remaining_pages)} pages with {model}")
    start_time = time.time()

    logger.info(f"Loading {len(remaining_pages)} pages...")
    load_start = time.time()

    requests = []
    page_data_map = {}
    printed_numbers = {}

    completed_pages = stage_storage.list_completed_pages(storage)
    for page_num in sorted(completed_pages):
        if page_num < min(remaining_pages):
            try:
                prev_data = storage.stage("label-pages").load_page(page_num, schema=output_schema)
                if prev_data and 'printed_page_number' in prev_data:
                    printed_numbers[page_num] = prev_data['printed_page_number']
            except:
                pass

    def load_page(page_num):
        try:
            prev_page_number = None
            if page_num > 1 and (page_num - 1) in printed_numbers:
                prev_page_number = printed_numbers[page_num - 1]

            request, ocr_page = prepare_label_request(
                page_num=page_num,
                storage=storage,
                model=model,
                total_pages=total_pages,
                prev_page_number=prev_page_number,
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

    stage_log_dir = storage.stage("label-pages").output_dir / "logs"
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
            label_data = result.parsed_json
            if label_data is None:
                raise ValueError("parsed_json is None for successful result")

            total_blocks = len(label_data.get('blocks', []))
            avg_classification_confidence = (
                sum(b.get('classification_confidence', 0) for b in label_data.get('blocks', []))
                / total_blocks if total_blocks > 0 else 0.0
            )

            page_output = {
                'page_number': page_num,
                'printed_page_number': label_data.get('printed_page_number'),
                'numbering_style': label_data.get('numbering_style'),
                'page_number_location': label_data.get('page_number_location'),
                'page_number_confidence': label_data.get('page_number_confidence', 1.0),
                'page_region': label_data.get('page_region'),
                'page_region_confidence': label_data.get('page_region_confidence'),
                'blocks': label_data['blocks'],
                'model_used': model,
                'processing_cost': result.cost_usd,
                'timestamp': datetime.now().isoformat(),
                'total_blocks': total_blocks,
                'avg_classification_confidence': avg_classification_confidence,
            }

            validated = output_schema(**page_output)

            if validated.printed_page_number:
                printed_numbers[page_num] = validated.printed_page_number

            has_chapter_heading = any(
                b.classification == BlockType.CHAPTER_HEADING
                for b in validated.blocks
            )
            has_section_heading = any(
                b.classification == BlockType.SECTION_HEADING
                for b in validated.blocks
            )

            metrics = LabelPagesPageMetrics(**llm_result_to_metrics(
                result=result,
                page_num=page_num,
                extra_fields={
                    "total_blocks_classified": total_blocks,
                    "avg_classification_confidence": avg_classification_confidence,
                    "page_number_extracted": validated.printed_page_number is not None,
                    "page_region_classified": validated.page_region is not None,
                    "printed_page_number": validated.printed_page_number,
                    "numbering_style": validated.numbering_style,
                    "page_region": validated.page_region,
                    "has_chapter_heading": has_chapter_heading,
                    "has_section_heading": has_section_heading,
                    "chapter_heading_text": None,  # Text extraction happens in merged stage
                }
            ))

            stage_storage.save_labeled_page(
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
        f"Labeling complete: {batch_stats['completed']} succeeded, "
        f"{batch_stats['failed']} failed, "
        f"${batch_stats['total_cost_usd']:.4f} in {elapsed:.1f}s"
    )

    if failed_pages:
        logger.warning(f"Failed pages: {sorted(failed_pages)[:10]}")
