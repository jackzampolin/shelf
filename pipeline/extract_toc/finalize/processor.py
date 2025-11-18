"""
Finalize: Apply corrections and assemble final ToC.

Loads raw entries from detection, applies corrections from validation
(including assembly operations like merges/deletions), and builds final ToC.
"""

import json
from typing import Dict, List
from infra.pipeline.status import PhaseStatusTracker
from ..schemas import PageRange


def apply_corrections(tracker: PhaseStatusTracker, **kwargs) -> Dict:
    """
    Apply corrections and assemble final ToC.

    Loads:
    - Raw page_XXXX.json files from detection (phase 1)
    - corrections.json from validation (phase 2)

    Applies corrections (including deletions for merged entries)
    and builds final assembled ToC structure.
    """
    tracker.logger.info("=== Assembling final ToC and applying corrections ===")

    storage = tracker.storage
    stage_storage = tracker.stage_storage

    # Load raw ToC entries from detection phase
    # finder_result.json comes from find phase (phase 1, same stage)
    finder_result = stage_storage.load_file("finder_result.json")
    toc_range = PageRange(**finder_result["toc_page_range"])

    raw_entries = []
    for page_num in range(toc_range.start_page, toc_range.end_page + 1):
        page_file = f"page_{page_num:04d}.json"
        try:
            page_data = stage_storage.load_file(page_file)
            page_entries = page_data.get("entries", [])
            for entry in page_entries:
                entry["_source_page"] = page_num
                raw_entries.append(entry)
        except FileNotFoundError:
            tracker.logger.warning(f"Missing ToC page file: {page_file}")

    if not raw_entries:
        tracker.logger.warning("No raw entries found from detection phase")
        return _build_empty_toc(tracker, toc_range)

    tracker.logger.info(f"Loaded {len(raw_entries)} raw entries")

    # Load corrections from validation phase
    corrections_data = stage_storage.load_file("corrections.json")
    corrections = corrections_data.get("corrections", [])

    tracker.logger.info(f"Applying {len(corrections)} corrections")

    # Apply corrections to raw entries
    entries = raw_entries.copy()
    applied_count, failed_corrections = _apply_corrections_to_entries(
        entries, corrections, tracker
    )

    # Filter out deleted entries (from assembly merges)
    entries_before_filter = len(entries)
    entries = [e for e in entries if not e.get("_delete", False)]
    deleted_count = entries_before_filter - len(entries)

    if deleted_count > 0:
        tracker.logger.info(f"Removed {deleted_count} merged/duplicate entries")

    # Clean up internal fields
    for entry in entries:
        entry.pop("_source_page", None)
        entry.pop("_delete", None)

    # Build final ToC structure
    final_toc = _build_final_toc(entries, toc_range)

    # Save final ToC
    output_path = tracker.phase_dir / "toc.json"
    output_path.write_text(json.dumps(final_toc, indent=2))
    tracker.logger.info(
        f"Saved final ToC: {len(entries)} entries "
        f"({applied_count} corrections, {deleted_count} merged)"
    )

    # Record metrics
    tracker.metrics_manager.record(
        key=f"{tracker.metrics_prefix}finalize",
        cost_usd=0.0,
        time_seconds=0.0,
        custom_metrics={
            "raw_entries": len(raw_entries),
            "final_entries": len(entries),
            "corrections_applied": applied_count,
            "corrections_failed": len(failed_corrections),
            "entries_deleted": deleted_count,
        }
    )

    return final_toc


def _apply_corrections_to_entries(
    entries: List[Dict],
    corrections: List[Dict],
    tracker: PhaseStatusTracker
) -> tuple[int, List[Dict]]:
    """
    Apply corrections to entries list.

    Returns (applied_count, failed_corrections).
    """
    applied_count = 0
    failed_corrections = []

    # Group corrections by entry_index
    corrections_by_entry = {}
    for corr in corrections:
        idx = corr["entry_index"]
        if idx not in corrections_by_entry:
            corrections_by_entry[idx] = []
        corrections_by_entry[idx].append(corr)

    # Apply corrections
    for entry_idx, entry_corrections in corrections_by_entry.items():
        if entry_idx < 0 or entry_idx >= len(entries):
            failed_corrections.append({
                "entry_index": entry_idx,
                "error": f"Invalid entry index (out of range 0-{len(entries)-1})"
            })
            continue

        entry = entries[entry_idx]

        for corr in entry_corrections:
            field = corr["field"]
            old_value = corr.get("old")
            new_value = corr["new"]
            confidence = corr.get("confidence", 0.0)

            # Special handling for _delete field (assembly merges)
            if field == "_delete":
                entry["_delete"] = new_value
                applied_count += 1
                tracker.logger.info(
                    f"  Entry {entry_idx}: Marked for deletion "
                    f"(merged into another entry) (conf={confidence:.2f})"
                )
                continue

            # Validate field exists
            if field not in entry and old_value is not None:
                failed_corrections.append({
                    **corr,
                    "error": f"Field '{field}' not found in entry"
                })
                continue

            # For new fields or null old values, just set
            if old_value is None or field not in entry:
                entry[field] = new_value
                applied_count += 1
                tracker.logger.info(
                    f"  Entry {entry_idx}.{field}: (new) → '{new_value}' "
                    f"(conf={confidence:.2f})"
                )
                continue

            current_value = entry[field]

            # Check old value matches (safety check)
            if current_value != old_value:
                tracker.logger.warning(
                    f"  Entry {entry_idx}: Field '{field}' mismatch - "
                    f"expected '{old_value}', found '{current_value}'. Skipping."
                )
                failed_corrections.append({
                    **corr,
                    "error": f"Old value mismatch: expected '{old_value}', found '{current_value}'"
                })
                continue

            # Apply correction
            entry[field] = new_value
            applied_count += 1

            tracker.logger.info(
                f"  Entry {entry_idx}.{field}: '{old_value}' → '{new_value}' "
                f"(conf={confidence:.2f})"
            )

    if failed_corrections:
        tracker.logger.warning(f"Failed to apply {len(failed_corrections)} corrections")
        for fail in failed_corrections[:5]:  # Show first 5
            tracker.logger.warning(f"  Entry {fail['entry_index']}: {fail.get('error', 'unknown error')}")

    return applied_count, failed_corrections


def _build_final_toc(entries: List[Dict], toc_range: PageRange) -> Dict:
    """Build final ToC structure."""
    # Count entries by level
    entries_by_level = {}
    for entry in entries:
        level = entry.get("level", 1)
        entries_by_level[level] = entries_by_level.get(level, 0) + 1

    return {
        "toc": {
            "entries": entries,
            "toc_page_range": {
                "start_page": toc_range.start_page,
                "end_page": toc_range.end_page
            },
            "entries_by_level": {str(k): v for k, v in entries_by_level.items()},
            "parsing_confidence": 0.95,  # High confidence after validation
            "notes": ["Assembled and validated with label-structure cross-check"]
        },
        "validation": {
            "method": "agent_assembly_and_validation",
            "label_structure_cross_check": True
        },
        "search_strategy": "vision_agent_with_ocr_and_validation"
    }


def _build_empty_toc(tracker: PhaseStatusTracker, toc_range: PageRange) -> Dict:
    """Build empty ToC structure when no entries found."""
    tracker.logger.warning("Building empty ToC (no entries found)")
    return {
        "toc": {
            "entries": [],
            "toc_page_range": {
                "start_page": toc_range.start_page,
                "end_page": toc_range.end_page
            },
            "entries_by_level": {},
            "parsing_confidence": 0.0,
            "notes": ["No entries found"]
        }
    }
