import json

from infra.llm.models import LLMResult
from infra.pipeline.logger import PipelineLogger
from infra.pipeline.storage.book_storage import BookStorage

from ..schemas import ToCEntry


def create_toc_handler(
    storage: BookStorage,
    logger: PipelineLogger,
    phase_name: str = "detection",
):
    stage_storage = storage.stage('extract-toc')

    def on_result(result: LLMResult):
        if result.success:
            page_num = int(result.request.id.split('_')[1])

            try:
                response_data = json.loads(result.response)

                entries_raw = response_data.get("entries", [])
                entries_validated = []

                for entry in entries_raw:
                    try:
                        validated_entry = ToCEntry(**entry)
                        entries_validated.append(validated_entry.model_dump())
                    except Exception as e:
                        logger.error(f"Page {page_num}: Invalid entry {entry}: {e}")

                page_result = {
                    "page_num": page_num,
                    "entries": entries_validated,
                    "page_metadata": response_data.get("page_metadata", {}),
                    "confidence": response_data.get("confidence", 0.0),
                    "notes": response_data.get("notes", "")
                }

                stage_storage.save_file(
                    f"{result.request.id}.json",
                    page_result
                )

                result.record_to_metrics(
                    metrics_manager=stage_storage.metrics_manager,
                    key=f"{phase_name}_{result.request.id}",
                    extra_fields={'phase': 'detection', 'entries_found': len(entries_validated)}
                )

                logger.info(
                    f"✓ {result.request.id}: {len(entries_validated)} entries extracted"
                )

            except Exception as e:
                logger.error(
                    f"✗ {result.request.id}: Failed to parse response",
                    request_id=result.request.id,
                    error=str(e)
                )
        else:
            logger.error(
                f"✗ {result.request.id}: ToC extraction failed",
                request_id=result.request.id,
                error_type=result.error_type,
                error=result.error_message,
                attempts=result.attempts,
                execution_time=result.execution_time_seconds,
                model=result.model_used
            )

    return on_result
