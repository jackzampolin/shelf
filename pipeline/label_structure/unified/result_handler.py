from infra.llm.models import LLMResult
from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from ..schemas.unified import UnifiedExtractionOutput


def create_result_handler(
    storage: BookStorage,
    logger: PipelineLogger,
):
    stage_storage = storage.stage("label-structure")

    def on_result(result: LLMResult):
        if result.success:
            if result.parsed_json is None:
                logger.error(
                    f"✗ Unified extraction returned None: {result.request.id}",
                    request_id=result.request.id,
                    error="LLM returned null/empty response - should have been caught by executor"
                )
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

            # Log summary
            data = result.parsed_json
            header_present = data.get('header', {}).get('present', False)
            footer_present = data.get('footer', {}).get('present', False)
            page_num = data.get('page_number', {}).get('number', '')
            markers_count = len(data.get('markers', []))
            footnotes_count = len(data.get('footnotes', []))
            xrefs_count = len(data.get('cross_references', []))

            parts = []
            if header_present:
                parts.append("hdr")
            if footer_present:
                parts.append("ftr")
            if page_num:
                parts.append(f"p{page_num}")
            if markers_count:
                parts.append(f"{markers_count}mkr")
            if footnotes_count:
                parts.append(f"{footnotes_count}fn")
            if xrefs_count:
                parts.append(f"{xrefs_count}xref")

            summary = ", ".join(parts) if parts else "empty"
            logger.info(f"✓ {result.request.id}: {summary}")
        else:
            logger.error(
                f"✗ Unified extraction failed: {result.request.id}",
                request_id=result.request.id,
                error_type=result.error_type,
                error=result.error_message,
                attempts=result.attempts,
                execution_time=result.execution_time_seconds,
                model=result.model_used
            )

    return on_result
