"""Stage 2 result handler - merges Stage 1 + Stage 2, saves final output"""

from infra.llm.batch_client import LLMResult
from infra.llm.metrics import llm_result_to_metrics


def create_stage2_handler(storage, stage_storage, logger, model, output_schema, ocr_pages, stage_name):
    """Create Stage 2 result handler (merges Stage 1 + Stage 2, saves final output)."""

    def on_result(result: LLMResult):
        if result.success:
            page_num = result.request.metadata['page_num']
            ocr_page = ocr_pages[page_num]
            label_data = result.parsed_json

            # Load Stage 1 results for merging
            # Stage 1 is the authoritative source for page-level metadata
            stage1_results = stage_storage.load_stage1_result(storage, page_num)

            # Build final output combining Stage 1 + Stage 2
            from datetime import datetime, timezone

            # Extract Stage 1 data (page-level metadata)
            page_number_data = stage1_results.get('page_number', {})
            page_region_data = stage1_results.get('page_region', {})
            sequence_validation = page_number_data.get('sequence_validation', {})

            page_output = {
                "page_number": page_num,
                # Page-level metadata from Stage 1 (3-image structural analysis)
                "printed_page_number": page_number_data.get('printed_number'),
                "numbering_style": page_number_data.get('numbering_style'),
                "page_number_location": page_number_data.get('location'),
                "page_number_confidence": sequence_validation.get('confidence', 1.0),
                "page_region": page_region_data.get('region'),
                "page_region_confidence": page_region_data.get('confidence'),
                # Block-level classifications from Stage 2 (focused block analysis)
                "blocks": label_data.get('blocks', []),
                "model_used": model,
                "processing_cost": result.cost_usd or 0.0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "total_blocks": len(label_data.get('blocks', [])),
                "avg_classification_confidence": sum(
                    b.get('classification_confidence', 0.0) for b in label_data.get('blocks', [])
                ) / max(len(label_data.get('blocks', [])), 1),
            }

            # Build metrics
            metrics_data = llm_result_to_metrics(
                result=result,
                page_num=page_num,
                extra_fields={
                    'total_blocks_classified': len(label_data.get('blocks', [])),
                    'avg_classification_confidence': page_output['avg_classification_confidence'],
                    'page_number_extracted': stage1_results.get('page_number', {}).get('printed_number') is not None,
                    'page_region_classified': True,
                    'printed_page_number': stage1_results.get('page_number', {}).get('printed_number'),
                    'numbering_style': page_number_data.get('numbering_style'),
                    'page_region': page_region_data.get('region'),
                    'has_chapter_heading': any(
                        b.get('classification') in ['CHAPTER_HEADING', 'PART_HEADING']
                        for b in label_data.get('blocks', [])
                    ),
                    'has_section_heading': any(
                        b.get('classification') in ['SECTION_HEADING', 'SUBSECTION_HEADING', 'SUBSUBSECTION_HEADING']
                        for b in label_data.get('blocks', [])
                    ),
                    'chapter_heading_text': next(
                        (b.get('text') for b in label_data.get('blocks', [])
                         if b.get('classification') in ['CHAPTER_HEADING', 'PART_HEADING']),
                        None
                    ),
                }
            )

            # Save final output with metrics
            stage_storage.save_stage2_result(
                storage=storage,
                page_num=page_num,
                data=page_output,
                schema=output_schema,
                cost_usd=result.cost_usd or 0.0,
                metrics=metrics_data,
            )

            logger.info(f"✓ Stage 2 complete: page {page_num}")
        else:
            page_num = result.request.metadata.get('page_num', 'unknown')
            logger.error(f"✗ Stage 2 failed: page {page_num}", error=result.error)

    return on_result
