from infra.llm.models import LLMResult
from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from ..schemas.structure import StructuralMetadataOutput


def create_result_handler(
    storage: BookStorage,
    logger: PipelineLogger,
):
    stage_storage = storage.stage("label-structure")

    def on_result(result: LLMResult):
        if result.success:
            # Guard against None/null parsed_json
            # NOTE: This shouldn't happen - executor should catch this earlier
            # But if it does, just log it and don't save anything (will be retried)
            if result.parsed_json is None:
                logger.error(
                    f"✗ Structure extraction returned None: {result.request.id}",
                    request_id=result.request.id,
                    error="LLM returned null/empty response - should have been caught by executor"
                )
                return

            stage_storage.save_file(
                f"structure/{result.request.id}.json",
                result.parsed_json,
                schema=StructuralMetadataOutput
            )

            result.record_to_metrics(
                metrics_manager=stage_storage.metrics_manager,
                key=f"structure_{result.request.id}",
            )

            header_present = result.parsed_json.get('header', {}).get('present', False)
            footer_present = result.parsed_json.get('footer', {}).get('present', False)
            page_num_present = result.parsed_json.get('page_number', {}).get('present', False)
            logger.info(
                f"✓ {result.request.id}: "
                f"header={header_present}, footer={footer_present}, page#={page_num_present}"
            )
        else:
            logger.error(
                f"✗ Structure extraction failed: {result.request.id}",
                request_id=result.request.id,
                error_type=result.error_type,
                error=result.error_message,
                attempts=result.attempts,
                execution_time=result.execution_time_seconds,
                model=result.model_used
            )

    return on_result
