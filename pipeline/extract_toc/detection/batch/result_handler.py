import json
from typing import List, Dict, Callable

from infra.llm.models import LLMResult
from infra.llm.metrics import record_llm_result
from infra.pipeline.logger import PipelineLogger
from infra.pipeline.storage.book_storage import BookStorage

from ...schemas import ToCEntry


def create_toc_handler(
    storage: BookStorage,
    logger: PipelineLogger,
    page_results: List[Dict]
) -> Callable[[LLMResult], None]:
    """Create result handler for ToC entry extraction.

    Args:
        storage: BookStorage for accessing metrics_manager
        logger: Pipeline logger
        page_results: Shared list to collect results

    Returns:
        Handler function that validates and stores results
    """
    stage_storage = storage.stage('extract-toc')

    def handle_result(result: LLMResult):
        """Handle completed ToC entry extraction result."""
        if result.success:
            page_num = result.request.metadata["page_num"]

            try:
                response_data = json.loads(result.response)

                # Validate entries against ToCEntry schema
                entries_raw = response_data.get("entries", [])
                entries_validated = []

                for entry in entries_raw:
                    try:
                        validated_entry = ToCEntry(**entry)
                        entries_validated.append(validated_entry.model_dump())
                    except Exception as e:
                        logger.error(f"  Page {page_num}: Invalid entry {entry}: {e}")

                page_results.append({
                    "page_num": page_num,
                    "entries": entries_validated,
                    "page_metadata": response_data.get("page_metadata", {}),
                    "confidence": response_data.get("confidence", 0.0),
                    "notes": response_data.get("notes", "")
                })

                # Record metrics
                record_llm_result(
                    metrics_manager=stage_storage.metrics_manager,
                    key=f"page_{page_num:04d}",
                    result=result,
                    page_num=page_num,
                    extra_fields={'phase': 'detection', 'entries_found': len(entries_validated)}
                )

            except Exception as e:
                logger.error(f"  Page {page_num}: Failed to parse ToC entry extraction: {e}")
        else:
            page_num = result.request.metadata["page_num"]
            logger.error(f"  Page {page_num}: Failed to extract ToC entries: {result.error_message}")

    return handle_result
