from typing import Dict, Optional, Any
from .extractor import extract_mechanical_patterns
from infra.pipeline.status import PhaseStatusTracker
from ..schemas.mechanical import MechanicalExtractionOutput


def process_mechanical_extraction(
    tracker: PhaseStatusTracker,
    **kwargs: Optional[Dict[str, Any]],
) -> None:
    tracker.logger.info(f"mechanical pattern extraction starting")
    remaining_pages = tracker.get_remaining_items()
    if not remaining_pages:
        tracker.logger.info("No pages to process (all completed)")
        return

    tracker.logger.info(f"processing {len(remaining_pages)} pages")

    processed = 0
    failed_pages = []

    for page_num in remaining_pages:
        try:
            mistral_data = tracker.storage.stage("mistral-ocr").load_page(page_num)
            olm_data = tracker.storage.stage("olm-ocr").load_page(page_num)
            paddle_data = tracker.storage.stage("paddle-ocr").load_page(page_num)

            mistral_markdown = mistral_data.get("markdown", "")
            olm_text = olm_data.get("text", "")
            paddle_text = paddle_data.get("text", "")

            result = extract_mechanical_patterns(
                mistral_markdown=mistral_markdown,
                olm_text=olm_text,
                paddle_text=paddle_text
            )

            tracker.storage.stage("label-structure").save_file(
                f"mechanical/page_{page_num:04d}.json",
                result.model_dump(),
                schema=MechanicalExtractionOutput
            )

            processed += 1

            hints = result.pattern_hints
            pattern_summary = []
            if result.headings_present:
                pattern_summary.append(f"{len(result.headings)}h")
            if hints.has_mistral_footnote_refs:
                pattern_summary.append(f"{hints.mistral_footnote_count}fn")
            if hints.has_mistral_endnote_refs:
                pattern_summary.append(f"{len(hints.mistral_endnote_markers)}en")
            if hints.has_repeated_symbols:
                pattern_summary.append(f"{hints.repeated_symbol_count}{hints.repeated_symbol}")
            if hints.has_olm_chart_tags:
                pattern_summary.append(f"{hints.olm_chart_count}chart")
            if hints.has_mistral_images:
                pattern_summary.append(f"{len(hints.mistral_image_refs)}img")

            if pattern_summary:
                tracker.logger.info(
                    f"✓ page_{page_num:04d}: {', '.join(pattern_summary)}"
                )
            else:
                tracker.logger.debug(f"✓ page_{page_num:04d}: no patterns")

        except Exception as e:
            tracker.logger.error(
                f"✗ Failed to process page_{page_num:04d}: {e}",
                page_num=page_num,
                error=str(e),
                error_type=type(e).__name__
            )
            failed_pages.append({"page": page_num, "error": str(e), "error_type": type(e).__name__})

    if failed_pages:
        import json
        error_file = tracker.phase_dir / "mechanical_errors.json"
        error_file.write_text(json.dumps(failed_pages, indent=2))
        raise ValueError(f"{len(failed_pages)} pages failed mechanical extraction - see {error_file}")

    tracker.logger.info(f"Mechanical extraction complete: {processed}/{len(remaining_pages)} pages processed")
