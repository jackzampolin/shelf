from infra.llm.models import LLMResult
from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from ..schemas.annotations import AnnotationsOutput


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
                    f"✗ Annotations extraction returned None: {result.request.id}",
                    request_id=result.request.id,
                    error="LLM returned null/empty response - should have been caught by executor"
                )
                return

            stage_storage.save_file(
                f"annotations/{result.request.id}.json",
                result.parsed_json,
                schema=AnnotationsOutput
            )

            result.record_to_metrics(
                metrics_manager=stage_storage.metrics_manager,
                key=f"annotations_{result.request.id}",
            )

            markers_present = result.parsed_json.get('markers_present', False)
            footnotes_present = result.parsed_json.get('footnotes_present', False)
            cross_refs_present = result.parsed_json.get('cross_references_present', False)
            markers_count = len(result.parsed_json.get('markers', []))
            footnotes_count = len(result.parsed_json.get('footnotes', []))
            cross_refs_count = len(result.parsed_json.get('cross_references', []))

            logger.info(
                f"✓ {result.request.id}: "
                f"markers={markers_count}, footnotes={footnotes_count}, cross-refs={cross_refs_count}"
            )
        else:
            logger.error(
                f"✗ Annotations extraction failed: {result.request.id}",
                request_id=result.request.id,
                error_type=result.error_type,
                error=result.error_message,
                attempts=result.attempts,
                execution_time=result.execution_time_seconds,
                model=result.model_used
            )

    return on_result
