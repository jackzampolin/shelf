"""Stage 2 processor: Block-level classification with Stage 1 context."""

from concurrent.futures import ThreadPoolExecutor
from typing import List

from infra.llm.batch_client import LLMBatchProcessor, LLMResult
from infra.llm.utils import llm_result_to_metrics
from infra.storage.book_storage import BookStorage
from infra.storage.checkpoint import CheckpointManager
from infra.pipeline.logger import PipelineLogger


def process_stage2(
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
    """
    Run Stage 2: Block classification with Stage 1 context.

    Args:
        storage: Book storage
        checkpoint: Checkpoint manager
        logger: Pipeline logger
        stage_storage: Label pages stage storage
        model: Vision model to use
        max_workers: Max parallel workers
        max_retries: Max retry attempts
        remaining_pages: Pages that need Stage 2 processing
        total_pages: Total pages in book
        output_schema: Final output schema (LabelPagesPageOutput)
    """
    if not remaining_pages:
        logger.info("No pages need Stage 2 processing")
        return

    logger.info(f"Stage 2: Processing {len(remaining_pages)} pages with Stage 1 context")
    logger.info(f"Model: {model}, Workers: {max_workers}")

    # Prepare Stage 2 requests in parallel
    from ..vision.caller_stage2 import prepare_stage2_request

    logger.info(f"Loading {len(remaining_pages)} pages with Stage 1 context...")
    requests = []
    ocr_pages = {}

    def prepare_request(page_num):
        try:
            # Load Stage 1 results
            stage1_results = stage_storage.load_stage1_result(storage, page_num)
            if not stage1_results:
                logger.warning(f"No Stage 1 results for page {page_num} - skipping Stage 2")
                return None

            request, ocr_page = prepare_stage2_request(
                page_num=page_num,
                storage=storage,
                model=model,
                total_pages=total_pages,
                stage1_results=stage1_results,
            )
            return request, ocr_page
        except Exception as e:
            logger.warning(f"Failed to prepare Stage 2 request for page {page_num}", error=str(e))
            return None

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(prepare_request, page_num): page_num for page_num in remaining_pages}
        for future in futures:
            result = future.result()
            if result:
                request, ocr_page = result
                requests.append(request)
                ocr_pages[request.metadata['page_num']] = ocr_page

    if not requests:
        logger.error("No valid Stage 2 requests prepared")
        return

    logger.info(f"Prepared {len(requests)} Stage 2 requests")

    # Process batch with LLMBatchProcessor
    stage_storage_dir = storage.stage(stage_storage.stage_name)
    log_dir = stage_storage_dir.output_dir / "logs" / "stage2"
    log_dir.mkdir(parents=True, exist_ok=True)

    processor = LLMBatchProcessor(
        checkpoint=checkpoint,
        logger=logger,
        model=model,
        log_dir=log_dir,
        max_retries=max_retries,
    )

    # Result handler: Save final labeled output
    def on_result(result: LLMResult):
        if result.success:
            page_num = result.metadata['page_num']
            ocr_page = ocr_pages[page_num]
            label_data = result.parsed_json

            # Load Stage 1 results for merging
            stage1_results = stage_storage.load_stage1_result(storage, page_num)

            # Build final output combining Stage 1 + Stage 2
            page_output = {
                "page_number": page_num,
                "printed_page_number": stage1_results.get('page_number', {}).get('printed_number'),
                "numbering_style": stage1_results.get('page_number', {}).get('numbering_style'),
                "page_region": stage1_results.get('page_region', {}).get('region'),
                "blocks": label_data.get('blocks', []),
                "model_used": model,
                "processing_cost": result.cost_usd or 0.0,
                "total_blocks": len(label_data.get('blocks', [])),
                "avg_classification_confidence": sum(
                    b.get('classification_confidence', 0.0) for b in label_data.get('blocks', [])
                ) / max(len(label_data.get('blocks', [])), 1),
            }

            # Validate and save
            validated = output_schema(**page_output)

            # Checkpoint metrics
            from ..schemas.page_metrics import LabelPagesPageMetrics
            metrics_data = llm_result_to_metrics(result, page_num)
            metrics_data.update({
                'total_blocks_classified': len(label_data.get('blocks', [])),
                'avg_classification_confidence': page_output['avg_classification_confidence'],
                'page_number_extracted': stage1_results.get('page_number', {}).get('printed_number') is not None,
                'page_region_classified': True,
                'printed_page_number': stage1_results.get('page_number', {}).get('printed_number'),
                'has_chapter_heading': any(
                    b.get('classification') in ['CHAPTER_HEADING', 'PART_HEADING']
                    for b in label_data.get('blocks', [])
                ),
                'has_section_heading': any(
                    b.get('classification') in ['SECTION_HEADING', 'SUBSECTION_HEADING', 'SUBSUBSECTION_HEADING']
                    for b in label_data.get('blocks', [])
                ),
            })
            metrics = LabelPagesPageMetrics(**metrics_data)

            # Save final output
            stage_storage.save_labeled_page(
                storage=storage,
                page_num=page_num,
                data=validated.model_dump(),
                schema=output_schema,
                cost_usd=result.cost_usd or 0.0,
                metrics=metrics.model_dump(),
            )

            logger.info(f"✓ Stage 2 complete: page {page_num}")
        else:
            page_num = result.metadata.get('page_num', 'unknown')
            logger.error(f"✗ Stage 2 failed: page {page_num}", error=result.error)

    processor.process_batch(
        requests=requests,
        on_result=on_result,
    )

    logger.info(f"Stage 2 complete: {len(requests)} pages processed")
