from typing import List
from infra.llm.batch import LLMBatchProcessor, LLMBatchConfig
from infra.pipeline.status import PhaseStatusTracker
from .request_builder import prepare_unified_request
from .result_handler import create_result_handler
from ..schemas.unified import UnifiedExtractionOutput


def _create_empty_output() -> dict:
    return UnifiedExtractionOutput(
        page_number={"present": False, "number": "", "location": "", "reasoning": "Empty page"},
        running_header={"present": False, "text": "", "reasoning": "Empty page"},
    ).model_dump()


def _handle_empty_pages(tracker: PhaseStatusTracker, remaining_pages: List[int]) -> List[int]:
    ocr_stage = tracker.storage.stage("ocr-pages")
    stage_storage = tracker.storage.stage("label-structure")

    pages_with_content = []
    empty_count = 0

    for page_num in remaining_pages:
        try:
            blend_data = ocr_stage.load_page(page_num, subdir="blend")
            blended_text = blend_data.get("markdown", "")
        except FileNotFoundError:
            blended_text = ""

        if not blended_text:
            stage_storage.save_file(
                f"unified/page_{page_num:04d}.json",
                _create_empty_output(),
                schema=UnifiedExtractionOutput
            )
            tracker.logger.info(f"✓ page_{page_num:04d}: empty")
            empty_count += 1
        else:
            pages_with_content.append(page_num)

    if empty_count > 0:
        tracker.logger.info(f"{empty_count} empty pages handled")

    return pages_with_content


def process_unified_extraction(tracker: PhaseStatusTracker, **kwargs):
    model = kwargs.get("model")
    max_workers = kwargs.get("max_workers")
    max_retries = kwargs.get("max_retries", 3)

    tracker.logger.info(f"unified extraction starting (model={model})")

    remaining_pages = tracker.get_remaining_items()
    pages_with_content = _handle_empty_pages(tracker, remaining_pages)

    if not pages_with_content:
        tracker.logger.info("all pages empty - no LLM calls needed")
        return {}

    original_get_remaining = tracker.get_remaining_items
    tracker.get_remaining_items = lambda: pages_with_content

    try:
        return LLMBatchProcessor(LLMBatchConfig(
            tracker=tracker,
            model=model,
            batch_name=tracker.phase_name,
            request_builder=prepare_unified_request,
            result_handler=create_result_handler(tracker),
            max_workers=max_workers,
            max_retries=max_retries,
        )).process()
    finally:
        tracker.get_remaining_items = original_get_remaining
