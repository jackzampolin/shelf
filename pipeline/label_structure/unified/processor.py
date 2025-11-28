from typing import Dict, Any
from infra.llm.batch import LLMBatchProcessor, LLMBatchConfig
from infra.pipeline.status import PhaseStatusTracker
from .request_builder import prepare_unified_request
from .result_handler import create_result_handler


def process_unified_extraction(
    tracker: PhaseStatusTracker,
    **kwargs
) -> Dict[str, Any]:
    """Process unified structure + annotations extraction using LLM batch processor.

    This replaces the separate structure and annotations phases with a single
    LLM call per page, using the blended OCR as primary input.

    Args:
        tracker: PhaseStatusTracker providing access to storage, logger, status
        **kwargs: Optional configuration (model, max_workers, max_retries)
    """
    model = kwargs.get("model")
    max_workers = kwargs.get("max_workers")
    max_retries = kwargs.get("max_retries", 3)

    tracker.logger.info(f"=== Unified: Structure + Annotations extraction ===")
    tracker.logger.info(f"Model: {model}")

    return LLMBatchProcessor(LLMBatchConfig(
        tracker=tracker,
        model=model,
        batch_name="label-structure-unified",
        request_builder=prepare_unified_request,
        result_handler=create_result_handler(
            tracker.storage,
            tracker.logger,
        ),
        max_workers=max_workers,
        max_retries=max_retries,
    )).process()
