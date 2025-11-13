from typing import Dict, Any
from infra.llm.batch import LLMBatchProcessor, LLMBatchConfig
from infra.pipeline.status import BatchBasedStatusTracker
from .request_builder import prepare_annotations_request
from .result_handler import create_result_handler


def process_annotations(
    tracker: BatchBasedStatusTracker,
    model: str,
    max_workers: int,
    max_retries: int,
) -> Dict[str, Any]:
    tracker.logger.info(f"=== Annotations: LLM content extraction ===")
    tracker.logger.info(f"Model: {model}")

    output_dir = tracker.storage.stage("label-structure").output_dir / "annotations"
    output_dir.mkdir(parents=True, exist_ok=True)

    return LLMBatchProcessor(LLMBatchConfig(
        tracker=tracker,
        model=model,
        batch_name="label-structure-annotations",
        request_builder=prepare_annotations_request,
        result_handler=create_result_handler(
            tracker.storage,
            tracker.logger,
        ),
        max_workers=max_workers,
        max_retries=max_retries,
    )).process()
