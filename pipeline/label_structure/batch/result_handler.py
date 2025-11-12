from infra.llm.models import LLMResult
from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from ..schemas.llm_response import StructureExtractionResponse

def create_result_handler(
    storage: BookStorage,
    logger: PipelineLogger,
):
    stage_storage = storage.stage("label-structure")

    def on_result(result: LLMResult):
        if result.success:
            stage_storage.save_file(
                f"{result.request.id}.json",
                result.parsed_json,
                schema=StructureExtractionResponse
            )

            result.record_to_metrics(
                metrics_manager=stage_storage.metrics_manager,
                key=result.request.id,
            )

            header_present = result.parsed_json.get('header', {}).get('present', False)
            footer_present = result.parsed_json.get('footer', {}).get('present', False)
            page_num_present = result.parsed_json.get('page_number', {}).get('present', False)
            headings_present = result.parsed_json.get('headings', {}).get('present', False)
            logger.info(
                f"✓ {result.request.id}: "
                f"header={header_present}, footer={footer_present}, "
                f"page#={page_num_present}, headings={headings_present}"
            )
        else:
            logger.error(
                f"✗ Label-structure failed: {result.request.id}",
                request_id=result.request.id,
                error_type=result.error_type,
                error=result.error_message,
                attempts=result.attempts,
                execution_time=result.execution_time_seconds,
                model=result.model_used
            )

    return on_result
