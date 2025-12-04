from typing import Dict, Any
from infra.llm.batch import LLMBatchProcessor, LLMBatchConfig
from infra.pipeline.status import PhaseStatusTracker
from .request_builder import prepare_blend_request
from .result_handler import create_result_handler


def process_blend(tracker: PhaseStatusTracker, **kwargs) -> Dict[str, Any]:
    model = kwargs.get("model")
    max_workers = kwargs.get("max_workers")
    max_retries = kwargs.get("max_retries", 3)

    return LLMBatchProcessor(LLMBatchConfig(
        tracker=tracker,
        model=model,
        batch_name=tracker.phase_name,
        request_builder=prepare_blend_request,
        result_handler=create_result_handler(tracker),
        max_workers=max_workers,
        max_retries=max_retries,
    )).process()
