"""Result handlers for Stage 1 and Stage 2 LLM batch processing."""

from infra.llm.batch_client import LLMResult
from infra.llm.utils import llm_result_to_metrics


def create_stage1_handler(storage, stage_storage, checkpoint, logger):
    """Create Stage 1 result handler (saves intermediate structural analysis)."""

    def on_result(result: LLMResult):
        if result.success:
            page_num = result.metadata['page_num']
            stage1_data = result.parsed_json

            # Save Stage 1 intermediate result
            stage_storage.save_stage1_result(
                storage=storage,
                page_num=page_num,
                stage1_data=stage1_data,
                cost_usd=result.cost_usd or 0.0,
            )

            # Track cost in checkpoint
            checkpoint.mark_completed(
                page_num=page_num,
                cost_usd=result.cost_usd or 0.0,
                metrics={'stage': 'stage1'},
            )

            logger.info(f"✓ Stage 1 complete: page {page_num}")
        else:
            page_num = result.metadata.get('page_num', 'unknown')
            logger.error(f"✗ Stage 1 failed: page {page_num}", error=result.error)

    return on_result


def create_stage2_handler(storage, stage_storage, checkpoint, logger, model, output_schema, ocr_pages):
    """Create Stage 2 result handler (merges Stage 1 + Stage 2, saves final output)."""

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

    return on_result
