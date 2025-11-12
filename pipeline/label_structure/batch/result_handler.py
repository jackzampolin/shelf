from infra.llm.models import LLMResult
from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger

def create_result_handler(
    storage: BookStorage,
    logger: PipelineLogger,
    stage_name: str,
    output_schema: type,
    model: str,
):
    stage_storage = storage.stage(stage_name)

    def on_result(result: LLMResult):
        if result.success:
            page_num = result.request.metadata['page_num']
            observations = result.parsed_json

            page_output = {
                "page_num": page_num,
                "header": observations.get('header', {}),
                "footer": observations.get('footer', {}),
                "page_number": observations.get('page_number', {}),
                "headings": observations.get('headings', {}),
            }

            stage_storage.save_page(
                page_num,
                page_output,
                schema=output_schema
            )

            result.record_to_metrics(
                metrics_manager=stage_storage.metrics_manager,
                key=f"page_{page_num:04d}",
                extra_fields={'stage': stage_name, 'model': model}
            )

            header_present = observations.get('header', {}).get('present', False)
            footer_present = observations.get('footer', {}).get('present', False)
            page_num_present = observations.get('page_number', {}).get('present', False)
            headings_present = observations.get('headings', {}).get('present', False)
            logger.info(
                f"✓ Page {page_num}: "
                f"header={header_present}, footer={footer_present}, "
                f"page#={page_num_present}, headings={headings_present}"
            )
        else:
            page_num = result.request.metadata.get('page_num', 'unknown')
            logger.error(
                f"✗ Label-structure failed: page {page_num}",
                page_num=page_num,
                error_type=result.error_type,
                error=result.error_message,
                attempts=result.attempts,
                execution_time=result.execution_time_seconds,
                model=result.model_used if hasattr(result, 'model_used') else model
            )

    return on_result
