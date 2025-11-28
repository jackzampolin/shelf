from typing import Dict, Optional, Any
from .extractor import extract_mechanical_patterns
from infra.pipeline.status import PhaseStatusTracker
from ..schemas.mechanical import MechanicalExtractionOutput


def process_mechanical_extraction(
    tracker: PhaseStatusTracker,
    **kwargs: Optional[Dict[str, Any]],
) -> None:
    """Process mechanical pattern extraction using blended OCR output.

    Extracts headings, footnote markers, symbols, and other patterns
    from the high-quality blended markdown. OLM text is loaded separately
    only for chart tag detection.
    """
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
            ocr_stage = tracker.storage.stage("ocr-pages")

            # Load blended OCR (primary source)
            blend_data = ocr_stage.load_page(page_num, subdir="blend")
            blended_markdown = blend_data.get("markdown", "")

            # Load OLM text only for chart tag detection
            try:
                olm_data = ocr_stage.load_page(page_num, subdir="olm")
                olm_text = olm_data.get("text", "")
            except FileNotFoundError:
                olm_text = ""

            result = extract_mechanical_patterns(
                blended_markdown=blended_markdown,
                olm_text=olm_text,
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
