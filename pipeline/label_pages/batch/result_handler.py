from datetime import datetime, timezone
from infra.llm.models import LLMResult
from infra.llm.metrics import record_llm_result


def create_stage1_handler(storage, logger, stage_name, output_schema, model):
    """Create handler that maps Stage 1 LLM response to LabelPagesPageOutput."""

    def on_result(result: LLMResult):
        if result.success:
            page_num = result.request.metadata['page_num']
            stage1_data = result.parsed_json

            # Direct mapping: Stage 1 response matches final output schema
            page_output = {
                "page_number": page_num,
                "is_boundary": stage1_data.get('is_boundary', False),
                "boundary_confidence": stage1_data.get('boundary_confidence', 0.0),
                "boundary_position": stage1_data.get('boundary_position', 'none'),
                "visual_signals": stage1_data.get('visual_signals', {}),
                "textual_signals": stage1_data.get('textual_signals', {}),
                "reasoning": stage1_data.get('reasoning', ''),
                "model_used": model,
                "processing_cost": result.cost_usd or 0.0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            # Save output using standard save_page
            stage_storage = storage.stage(stage_name)
            stage_storage.save_page(
                page_num,
                page_output,
                schema=output_schema
            )

            # Record metrics
            record_llm_result(
                metrics_manager=stage_storage.metrics_manager,
                key=f"page_{page_num:04d}",
                result=result,
                page_num=page_num,
                extra_fields={'stage': stage_name}
            )

            boundary_status = "BOUNDARY" if page_output["is_boundary"] else "continuation"
            confidence = page_output["boundary_confidence"]
            position = page_output["boundary_position"]
            logger.info(f"✓ Label-pages complete: page {page_num} [{boundary_status} @ {position}, conf={confidence:.2f}]")
        else:
            page_num = result.request.metadata.get('page_num', 'unknown')
            logger.error(f"✗ Label-pages failed: page {page_num}", error=result.error_message)

    return on_result
