from infra.llm.models import LLMResult
from infra.llm.metrics import record_llm_result


def create_margin_handler(storage, logger, stage_name):
    def on_result(result: LLMResult):
        if result.success:
            page_num = result.request.metadata['page_num']
            margin_obs = result.parsed_json

            stage_storage = storage.stage(stage_name)
            margin_dir = stage_storage.output_dir / "margin"
            margin_dir.mkdir(parents=True, exist_ok=True)

            margin_file = margin_dir / f"page_{page_num:04d}.json"
            with open(margin_file, 'w') as f:
                import json
                json.dump(margin_obs, f, indent=2)

            record_llm_result(
                metrics_manager=stage_storage.metrics_manager,
                key=f"margin_page_{page_num:04d}",
                result=result,
                page_num=page_num,
                extra_fields={'pass': 'margin'}
            )

            header = margin_obs.get('header', {})
            footer = margin_obs.get('footer', {})
            page_number = margin_obs.get('page_number', {})

            header_text = header.get('text', 'none') if header.get('exists') else 'none'
            footer_text = footer.get('text', 'none') if footer.get('exists') else 'none'
            page_num_text = page_number.get('number', 'none') if page_number.get('exists') else 'none'

            logger.info(f"✓ Margin {page_num}: header={header_text[:20]}, footer={footer_text[:20]}, num={page_num_text}")
        else:
            page_num = result.request.metadata.get('page_num', 'unknown')
            logger.error(f"✗ Margin observation failed: page {page_num}", error=result.error_message)

    return on_result
