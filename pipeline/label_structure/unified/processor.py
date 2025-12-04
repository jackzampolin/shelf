from typing import Dict, Any, List
from infra.llm.batch import LLMBatchProcessor, LLMBatchConfig
from infra.pipeline.status import PhaseStatusTracker
from .request_builder import prepare_unified_request
from .result_handler import create_result_handler
from ..schemas.unified import UnifiedExtractionOutput


def _create_empty_unified_output() -> dict:
    """Create an empty unified output for pages with no OCR content."""
    return UnifiedExtractionOutput(
        header={"present": False, "text": "", "confidence": "high", "source_provider": "blend"},
        footer={"present": False, "text": "", "confidence": "high", "source_provider": "blend"},
        page_number={"present": False, "number": "", "location": "", "confidence": "high", "source_provider": "blend"},
        markers_present=False,
        markers=[],
        footnotes_present=False,
        footnotes=[],
        cross_references_present=False,
        cross_references=[],
        has_horizontal_rule=False,
        has_small_text_at_bottom=False,
        confidence="high",
    ).model_dump()


def _handle_empty_pages(tracker: PhaseStatusTracker, remaining_pages: List[int]) -> List[int]:
    """Handle pages with empty blend output by creating stub unified files.

    Returns list of pages that have content and need LLM processing.
    """
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
            # Create stub unified output for empty pages
            stage_storage.save_file(
                f"unified/page_{page_num:04d}.json",
                _create_empty_unified_output(),
                schema=UnifiedExtractionOutput
            )
            tracker.logger.info(f"✓ page_{page_num:04d}: empty page (no OCR content)")
            empty_count += 1
        else:
            pages_with_content.append(page_num)

    if empty_count > 0:
        tracker.logger.info(f"Handled {empty_count} empty pages with stub outputs")

    return pages_with_content


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

    # First, handle empty pages by creating stub outputs
    remaining_pages = tracker.get_remaining_items()
    pages_with_content = _handle_empty_pages(tracker, remaining_pages)

    if not pages_with_content:
        tracker.logger.info("All remaining pages were empty - no LLM calls needed")
        return {}

    # Create a custom tracker that only processes pages with content
    # by temporarily overriding get_remaining_items
    original_get_remaining = tracker.get_remaining_items
    tracker.get_remaining_items = lambda: pages_with_content

    try:
        return LLMBatchProcessor(LLMBatchConfig(
            tracker=tracker,
            model=model,
            batch_name=tracker.phase_name,
            request_builder=prepare_unified_request,
            result_handler=create_result_handler(
                tracker.storage,
                tracker.logger,
            ),
            max_workers=max_workers,
            max_retries=max_retries,
        )).process()
    finally:
        # Restore original method
        tracker.get_remaining_items = original_get_remaining
