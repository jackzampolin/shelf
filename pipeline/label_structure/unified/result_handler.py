from infra.llm.models import LLMResult
from ..schemas.unified import UnifiedExtractionOutput


def create_result_handler(storage, logger):
    stage_storage = storage.stage("label-structure")

    def on_result(result: LLMResult):
        if result.success:
            if result.parsed_json is None:
                logger.error(f"✗ {result.request.id}: null response")
                return

            stage_storage.save_file(
                f"unified/{result.request.id}.json",
                result.parsed_json,
                schema=UnifiedExtractionOutput
            )

            result.record_to_metrics(
                metrics_manager=stage_storage.metrics_manager,
                key=f"unified_{result.request.id}",
            )

            data = result.parsed_json
            parts = []
            if page_num := data.get('page_number', {}).get('number'):
                parts.append(f"p{page_num}")
            if header := data.get('running_header', {}).get('text'):
                parts.append(f"h:{header[:20]}...")

            logger.info(f"✓ {result.request.id}: {', '.join(parts) if parts else 'empty'}")
        else:
            logger.error(f"✗ {result.request.id}: {result.error_message}")

    return on_result
