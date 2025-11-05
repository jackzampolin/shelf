from datetime import datetime, timezone
from infra.llm.batch_client import LLMResult


def create_stage1_handler(storage, stage_storage, logger, stage_name, output_schema, model):
    """Create handler that maps Stage 1 LLM response to final LabelPagesPageOutput."""

    def on_result(result: LLMResult):
        if result.success:
            page_num = result.request.metadata['page_num']
            stage1_data = result.parsed_json

            # Map Stage 1 response to final output schema
            page_number_data = stage1_data.get('page_number', {})
            page_region_data = stage1_data.get('page_region', {})
            structural_boundary_data = stage1_data.get('structural_boundary', {})
            has_toc = stage1_data.get('has_table_of_contents', False)

            page_output = {
                "page_number": page_num,

                # Page number metadata
                "printed_page_number": page_number_data.get('printed_number'),
                "numbering_style": page_number_data.get('numbering_style', 'none'),
                "page_number_location": page_number_data.get('location', 'none'),
                "page_number_confidence": page_number_data.get('sequence_validation', {}).get('confidence', 1.0),

                # Page region
                "page_region": page_region_data.get('region', 'body'),
                "page_region_confidence": page_region_data.get('confidence', 0.5),

                # Structural boundary (full object)
                "structural_boundary": structural_boundary_data,

                # Content flags
                "has_table_of_contents": has_toc,

                # Metadata
                "model_used": model,
                "processing_cost": result.cost_usd or 0.0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            # Save final output (no intermediate Stage 1 storage needed)
            stage_storage.save_final_output(
                storage=storage,
                page_num=page_num,
                data=page_output,
                schema=output_schema,
                cost_usd=result.cost_usd or 0.0,
                result=result,
            )

            logger.info(f"✓ Label-pages complete: page {page_num}")
        else:
            page_num = result.request.metadata.get('page_num', 'unknown')
            logger.error(f"✗ Label-pages failed: page {page_num}", error=result.error)

    return on_result
