"""
Result handler for body structure pass.

Saves BodyObservation to body/ subdirectory.
"""

from infra.llm.models import LLMResult
from infra.llm.metrics import record_llm_result


def create_body_handler(storage, logger, stage_name):
    """Create handler for body structure results."""

    def on_result(result: LLMResult):
        if result.success:
            page_num = result.request.metadata['page_num']
            body_obs = result.parsed_json

            # Save to body/ subdirectory
            stage_storage = storage.stage(stage_name)
            body_dir = stage_storage.output_dir / "body"
            body_dir.mkdir(parents=True, exist_ok=True)

            body_file = body_dir / f"page_{page_num:04d}.json"
            with open(body_file, 'w') as f:
                import json
                json.dump(body_obs, f, indent=2)

            # Record metrics
            record_llm_result(
                metrics_manager=stage_storage.metrics_manager,
                key=f"body/page_{page_num:04d}",
                result=result,
                page_num=page_num,
                extra_fields={'pass': 'body'}
            )

            # Log summary
            heading = body_obs.get('heading', {})
            whitespace = body_obs.get('whitespace', {})
            ornamental = body_obs.get('ornamental_break', {})

            heading_text = heading.get('text', 'none') if heading.get('exists') else 'none'
            whitespace_zones = whitespace.get('zones', [])
            ornamental_exists = "yes" if ornamental.get('exists') else "no"

            logger.info(f"✓ Body {page_num}: heading={heading_text[:30]}, whitespace={whitespace_zones}, ornamental={ornamental_exists}")
        else:
            page_num = result.request.metadata.get('page_num', 'unknown')
            logger.error(f"✗ Body observation failed: page {page_num}", error=result.error_message)

    return on_result
