import json
from pathlib import Path

from infra.pipeline.status import PhaseStatusTracker
from ..schemas.merged_output import LabelStructurePageOutput


def apply_healing_decisions(
    tracker: PhaseStatusTracker,
    **kwargs
) -> dict:
    """Apply healing decisions from agent runs to page files.

    Args:
        tracker: PhaseStatusTracker providing access to storage, logger, status
        **kwargs: Optional configuration (unused for this phase)
    """
    storage = tracker.storage
    logger = tracker.logger
    stage_storage = storage.stage("label-structure")
    healing_dir = stage_storage.output_dir / "healing"

    if not healing_dir.exists():
        logger.warning("No healing/ directory found - run gap healing agents first")
        return {
            "pages_updated": 0,
            "chapters_discovered": 0,
            "skipped": 0
        }

    decision_files = list(healing_dir.glob("page_*.json"))

    if not decision_files:
        logger.warning("No healing decision files found")
        return {
            "pages_updated": 0,
            "chapters_discovered": 0,
            "skipped": 0
        }

    logger.info(f"Applying {len(decision_files)} healing decisions")

    pages_updated = 0
    chapters_discovered = 0
    skipped = 0

    for decision_file in sorted(decision_files):
        try:
            with open(decision_file, 'r') as f:
                decision = json.load(f)

            scan_page = decision['scan_page']

            try:
                page_data = stage_storage.load_file(f"page_{scan_page:04d}.json")
            except Exception as e:
                logger.error(f"Failed to load page_{scan_page:04d}.json: {e}")
                skipped += 1
                continue

            if 'page_number_update' in decision:
                page_data['page_number'].update(decision['page_number_update'])

            if 'chapter_marker' in decision:
                page_data['chapter_marker'] = decision['chapter_marker']
                chapters_discovered += 1

            stage_storage.save_file(
                f"page_{scan_page:04d}.json",
                page_data,
                schema=LabelStructurePageOutput
            )

            pages_updated += 1

            cluster_type = decision.get('cluster_type', 'unknown')
            logger.debug(f"Applied healing: page {scan_page} ({cluster_type})")

        except Exception as e:
            logger.error(f"Failed to apply {decision_file.name}: {e}")
            skipped += 1

    logger.info(
        f"Healing applied: {pages_updated} pages updated, "
        f"{chapters_discovered} chapter markers added, "
        f"{skipped} skipped"
    )

    result = {
        "pages_updated": pages_updated,
        "chapters_discovered": chapters_discovered,
        "skipped": skipped
    }

    # Save artifact for tracker
    output_path = tracker.phase_dir / "healing_applied.json"
    output_path.write_text(json.dumps(result, indent=2))

    return result


def extract_chapter_markers(
    tracker: PhaseStatusTracker,
    **kwargs
) -> dict:
    """Extract discovered chapter markers from healing decisions.

    Args:
        tracker: PhaseStatusTracker providing access to storage, logger, status
        **kwargs: Optional configuration (unused for this phase)
    """
    logger = tracker.logger
    stage_storage = tracker.storage.stage("label-structure")
    healing_dir = stage_storage.output_dir / "healing"

    if not healing_dir.exists():
        logger.warning("No healing/ directory found")
        return {"chapters_found": 0}

    chapters = []

    for decision_file in healing_dir.glob("page_*.json"):
        try:
            with open(decision_file, 'r') as f:
                decision = json.load(f)

            if 'chapter_marker' in decision:
                marker = decision['chapter_marker']
                chapters.append({
                    'chapter_num': marker['chapter_num'],
                    'scan_page': decision['scan_page'],
                    'title': marker['chapter_title'],
                    'confidence': marker['confidence'],
                    'detected_from': marker.get('detected_from', 'unknown'),
                    'cluster_id': decision.get('cluster_id', 'unknown')
                })

        except Exception as e:
            logger.error(f"Failed to read {decision_file.name}: {e}")

    chapters.sort(key=lambda x: x['chapter_num'])

    if chapters:
        stage_storage.save_file(
            "discovered_chapters.json",
            {"chapters": chapters}
        )

        logger.info(f"Discovered {len(chapters)} chapter markers from gap healing")

        for ch in chapters[:5]:
            logger.info(
                f"  Chapter {ch['chapter_num']}: \"{ch['title']}\" "
                f"(page {ch['scan_page']}, confidence {ch['confidence']:.2f})"
            )

        if len(chapters) > 5:
            logger.info(f"  ... and {len(chapters) - 5} more")

    else:
        logger.info("No chapter markers discovered")

    # Save artifact for tracker
    result = {
        "chapters_discovered": len(chapters)
    }

    output_path = tracker.phase_dir / "discovered_chapters.json"
    output_path.write_text(json.dumps(result, indent=2))

    logger.info(
        f"Applied healing: {pages_updated} pages updated, "
        f"{len(chapters)} chapters discovered, {skipped} skipped"
    )

    return result
