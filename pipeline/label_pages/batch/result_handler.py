from datetime import datetime, timezone
from infra.llm.models import LLMResult


def create_stage1_handler(storage, logger, stage_name, output_schema, model):
    """Create handler that maps observation response to LabelPagesPageOutput."""

    def on_result(result: LLMResult):
        if result.success:
            page_num = result.request.metadata['page_num']
            observations = result.parsed_json

            # Direct mapping: observations match output schema
            page_output = {
                "scan_page_number": page_num,
                # Observations (already in correct structure from schema)
                "header": observations.get('header', {}),
                "footer": observations.get('footer', {}),
                "page_number": observations.get('page_number', {}),
                "heading": observations.get('heading', {}),
                "whitespace": observations.get('whitespace', {}),
                "ornamental_break": observations.get('ornamental_break', {}),
                "text_continuation": observations.get('text_continuation', {}),
                "footnotes": observations.get('footnotes', {}),
                # Metadata
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
            result.record_to_metrics(
                metrics_manager=stage_storage.metrics_manager,
                key=f"page_{page_num:04d}",
                page_num=page_num,
                extra_fields={'stage': stage_name}
            )

            # Log summary
            heading = observations.get('heading', {})
            heading_text = heading.get('text', 'none') if heading.get('exists') else 'none'
            whitespace_zones = observations.get('whitespace', {}).get('zones', [])
            logger.info(f"✓ Page {page_num}: heading={heading_text}, whitespace={whitespace_zones}")
        else:
            page_num = result.request.metadata.get('page_num', 'unknown')
            logger.error(f"✗ Label-pages failed: page {page_num}", error=result.error_message)

    return on_result
