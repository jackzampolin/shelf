"""
Result handler for content flow pass.

Saves ContentObservation to content/ subdirectory.
"""

from infra.llm.models import LLMResult
from infra.llm.metrics import record_llm_result


def create_content_handler(storage, logger, stage_name):
    """Create handler for content flow results."""

    def on_result(result: LLMResult):
        if result.success:
            page_num = result.request.metadata['page_num']
            content_obs = result.parsed_json

            # Save to content/ subdirectory
            stage_storage = storage.stage(stage_name)
            content_dir = stage_storage.output_dir / "content"
            content_dir.mkdir(parents=True, exist_ok=True)

            content_file = content_dir / f"page_{page_num:04d}.json"
            with open(content_file, 'w') as f:
                import json
                json.dump(content_obs, f, indent=2)

            # Record metrics
            record_llm_result(
                metrics_manager=stage_storage.metrics_manager,
                key=f"content/page_{page_num:04d}",
                result=result,
                page_num=page_num,
                extra_fields={'pass': 'content'}
            )

            # Log summary
            text_cont = content_obs.get('text_continuation', {})
            footnotes = content_obs.get('footnotes', {})

            from_prev = "yes" if text_cont.get('from_previous') else "no"
            to_next = "yes" if text_cont.get('to_next') else "no"
            has_footnotes = "yes" if footnotes.get('exists') else "no"

            logger.info(f"✓ Content {page_num}: from_prev={from_prev}, to_next={to_next}, footnotes={has_footnotes}")
        else:
            page_num = result.request.metadata.get('page_num', 'unknown')
            logger.error(f"✗ Content observation failed: page {page_num}", error=result.error_message)

    return on_result
