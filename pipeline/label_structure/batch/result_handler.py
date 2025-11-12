"""
Result handler for label-structure stage.

Takes LLM structure extraction response and builds LabelStructurePageOutput.
"""

from datetime import datetime, timezone

from infra.llm.models import LLMResult
from infra.llm.metrics import record_llm_result
from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from ..schemas import (
    LabelStructurePageOutput,
    HeaderObservation,
    FooterObservation,
    PageNumberObservation,
    HeadingObservation,
)


def create_result_handler(
    storage: BookStorage,
    logger: PipelineLogger,
    stage_name: str,
    output_schema: type,
    model: str,
):
    """
    Create result handler for label-structure batch processing.

    Args:
        storage: BookStorage instance
        logger: PipelineLogger instance
        stage_name: Name of stage (for storage)
        output_schema: Output schema class
        model: Model name for metadata

    Returns:
        Handler function
    """
    stage_storage = storage.stage(stage_name)

    def on_result(result: LLMResult):
        """Handle LLM structure extraction result."""
        if result.success:
            page_num = result.request.metadata['page_num']
            observations = result.parsed_json

            # Build page output
            page_output = {
                "page_num": page_num,
                "header": observations.get('header', {}),
                "footer": observations.get('footer', {}),
                "page_number": observations.get('page_number', {}),
                "headings": observations.get('headings', {}),
            }

            # Save output
            stage_storage.save_page(
                page_num,
                page_output,
                schema=output_schema
            )

            # Record metrics
            record_llm_result(
                metrics_manager=stage_storage.metrics_manager,
                key=f"page_{page_num:04d}",
                result=result,
                page_num=page_num,
                extra_fields={'stage': stage_name, 'model': model}
            )

            # Log summary
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
