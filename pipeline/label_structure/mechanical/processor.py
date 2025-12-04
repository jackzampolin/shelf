import json
from .extractor import extract_mechanical_patterns
from infra.pipeline.status import PhaseStatusTracker
from ..schemas.mechanical import MechanicalExtractionOutput


def process_mechanical_extraction(tracker: PhaseStatusTracker, **kwargs) -> None:
    tracker.logger.info("mechanical pattern extraction starting")
    remaining_pages = tracker.get_remaining_items()
    if not remaining_pages:
        tracker.logger.info("No pages to process")
        return

    tracker.logger.info(f"processing {len(remaining_pages)} pages")
    processed = 0
    failed_pages = []

    for page_num in remaining_pages:
        try:
            blend_data = tracker.storage.stage("ocr-pages").load_page(page_num, subdir="blend")
            result = extract_mechanical_patterns(blend_data.get("markdown", ""))

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
            if hints.has_footnote_refs:
                pattern_summary.append(f"{hints.footnote_count}fn")
            if hints.has_endnote_refs:
                pattern_summary.append(f"{len(hints.endnote_markers)}en")
            if hints.has_repeated_symbols:
                pattern_summary.append(f"{hints.repeated_symbol_count}{hints.repeated_symbol}")
            if hints.has_images:
                pattern_summary.append(f"{len(hints.image_refs)}img")

            if pattern_summary:
                tracker.logger.info(f"✓ page_{page_num:04d}: {', '.join(pattern_summary)}")
            else:
                tracker.logger.debug(f"✓ page_{page_num:04d}: no patterns")

        except Exception as e:
            tracker.logger.error(f"✗ page_{page_num:04d}: {e}", page_num=page_num, error=str(e))
            failed_pages.append({"page": page_num, "error": str(e)})

    if failed_pages:
        error_file = tracker.phase_dir / "mechanical_errors.json"
        error_file.write_text(json.dumps(failed_pages, indent=2))
        raise ValueError(f"{len(failed_pages)} pages failed - see {error_file}")

    tracker.logger.info(f"complete: {processed}/{len(remaining_pages)} pages")
