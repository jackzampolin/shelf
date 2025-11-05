from datetime import datetime, timezone
from infra.llm.batch_client import LLMResult


def create_stage1_handler(storage, stage_storage, logger, stage_name, output_schema, model):
    """Create handler that maps simplified Stage 1 LLM response to LabelPagesPageOutput."""

    def on_result(result: LLMResult):
        if result.success:
            page_num = result.request.metadata['page_num']
            stage1_data = result.parsed_json

            # Direct mapping: Stage 1 response matches final output schema
            page_output = {
                "page_number": page_num,
                "is_boundary": stage1_data.get('is_boundary', False),
                "boundary_confidence": stage1_data.get('boundary_confidence', 0.0),
                "visual_signals": stage1_data.get('visual_signals', {}),
                "textual_signals": stage1_data.get('textual_signals', {}),
                "heading_info": stage1_data.get('heading_info'),
                "reasoning": stage1_data.get('reasoning', ''),
                "model_used": model,
                "processing_cost": result.cost_usd or 0.0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            # Save final output
            stage_storage.save_final_output(
                storage=storage,
                page_num=page_num,
                data=page_output,
                schema=output_schema,
                cost_usd=result.cost_usd or 0.0,
                result=result,
            )

            boundary_status = "BOUNDARY" if page_output["is_boundary"] else "continuation"
            confidence = page_output["boundary_confidence"]
            logger.info(f"✓ Label-pages complete: page {page_num} [{boundary_status}, conf={confidence:.2f}]")
        else:
            page_num = result.request.metadata.get('page_num', 'unknown')
            logger.error(f"✗ Label-pages failed: page {page_num}", error=result.error)

    return on_result
