from typing import Dict, Any
from infra.llm.batch import LLMBatchProcessor, LLMBatchConfig
from infra.pipeline.status import PhaseStatusTracker
from .request_builder import prepare_structural_metadata_request
from .result_handler import create_result_handler


def process_structural_metadata(
    tracker: PhaseStatusTracker,
    **kwargs
) -> Dict[str, Any]:
    """Process structural metadata extraction using LLM batch processor.

    Args:
        tracker: PhaseStatusTracker providing access to storage, logger, status
        **kwargs: Optional configuration (model, max_workers, max_retries)
    """
    # Extract kwargs with defaults
    model = kwargs.get("model")
    max_workers = kwargs.get("max_workers")
    max_retries = kwargs.get("max_retries", 3)

    return LLMBatchProcessor(LLMBatchConfig(
        tracker=tracker,
        model=model,
        batch_name="label-structure-structure",
        request_builder=prepare_structural_metadata_request,
        result_handler=create_result_handler(
            tracker.storage,
            tracker.logger,
        ),
        max_workers=max_workers,
        max_retries=max_retries,
    )).process()
