"""Merge phase: Combine linked_toc + discovered entries into enriched_toc."""

from typing import List, Optional
from ..schemas import LinkedTableOfContents, PatternAnalysis
from ..schemas import EnrichedToCEntry, EnrichedTableOfContents


def merge_enriched_toc(tracker, **kwargs):
    """Merge linked ToC entries with discovered pattern entries."""
    storage = tracker.storage
    logger = tracker.logger
    stage_storage = tracker.stage_storage

    # Load linked ToC
    linked_toc_data = stage_storage.load_file("linked_toc.json")
    if not linked_toc_data:
        logger.warning("No linked_toc.json - cannot merge")
        return

    linked_toc = LinkedTableOfContents(**linked_toc_data)

    # Load pattern analysis for context
    pattern_data = stage_storage.load_file("pattern/pattern_analysis.json")
    pattern = PatternAnalysis(**pattern_data) if pattern_data else None

    # Load discovered entries
    discover_dir = stage_storage.output_dir / "discover"
    discovered_entries = []

    if discover_dir.exists():
        for result_file in sorted(discover_dir.glob("*.json")):
            result_data = stage_storage.load_file(f"discover/{result_file.name}")
            if result_data and result_data.get("found") and result_data.get("scan_page"):
                discovered_entries.append(result_data)

    logger.info(f"Merging {len(linked_toc.entries)} ToC entries + {len(discovered_entries)} discovered entries")

    # Build enriched entries from ToC
    enriched_entries = []
    entry_index = 0

    toc_entries = [e for e in linked_toc.entries if e is not None]

    # Separate valid and invalid ToC entries
    valid_toc_entries = []
    invalid_toc_entries = []

    for toc_entry in toc_entries:
        if toc_entry.scan_page is None:
            invalid_toc_entries.append(toc_entry)
            logger.warning(
                f"Skipping ToC entry '{toc_entry.title}' - no scan_page found"
            )
        else:
            valid_toc_entries.append(toc_entry)

    if invalid_toc_entries:
        logger.error(
            f"IMPORTANT: {len(invalid_toc_entries)}/{len(toc_entries)} ToC entries could not be linked. "
            f"Unlinked: {[e.title for e in invalid_toc_entries]}"
        )

    # Add ToC entries
    toc_index_map = {}
    for i, toc_entry in enumerate(valid_toc_entries):
        toc_index_map[i] = entry_index
        enriched_entries.append(EnrichedToCEntry(
            entry_index=entry_index,
            title=toc_entry.title,
            scan_page=toc_entry.scan_page,
            level=toc_entry.level,
            parent_index=None,
            source="toc",
            entry_number=toc_entry.entry_number,
            printed_page_number=toc_entry.printed_page_number
        ))
        entry_index += 1

    # Build set of pages that already have ToC entries
    toc_pages = {e.scan_page for e in valid_toc_entries}

    # Deduplicate discovered entries by identifier and page
    discovered_entries = _deduplicate_discovered(discovered_entries, pattern, logger)

    # Add discovered entries
    skipped_duplicates = 0
    for entry in discovered_entries:
        scan_page = entry["scan_page"]

        # Never add duplicate for a page that already has ToC entry
        if scan_page in toc_pages:
            logger.info(f"Skipping duplicate: '{entry['identifier']}' on page {scan_page} (ToC already has entry)")
            skipped_duplicates += 1
            continue

        # Find parent ToC entry
        parent_idx, parent_level = _find_parent_toc_entry(
            scan_page, valid_toc_entries, toc_index_map
        )

        # Use title from discover (generated from pattern format), otherwise identifier
        title = entry.get("title") or entry.get("identifier", "")
        identifier = entry.get("identifier", "")

        enriched_entries.append(EnrichedToCEntry(
            entry_index=entry_index,
            title=title,
            scan_page=scan_page,
            level=entry.get("level", parent_level + 1),
            parent_index=parent_idx,
            source="discovered",
            entry_number=identifier,
            discovery_reasoning=entry.get("reasoning", ""),
        ))
        entry_index += 1

    if skipped_duplicates:
        logger.warning(f"Skipped {skipped_duplicates} discovered entries that duplicated ToC pages")

    # Sort by page and reindex
    enriched_entries.sort(key=lambda e: e.scan_page)
    for i, entry in enumerate(enriched_entries):
        entry.entry_index = i

    # Create enriched ToC
    enriched_toc = EnrichedTableOfContents(
        entries=enriched_entries,
        original_toc_count=len(valid_toc_entries),
        discovered_count=len(discovered_entries) - skipped_duplicates,
        total_entries=len(enriched_entries),
    )

    stage_storage.save_file("enriched_toc.json", enriched_toc.model_dump())

    logger.info(f"Enriched ToC created: {len(enriched_entries)} total entries")
    logger.info(f"  Original ToC: {len(valid_toc_entries)}")
    logger.info(f"  Discovered: {len(discovered_entries) - skipped_duplicates}")


def _deduplicate_discovered(
    entries: List[dict],
    pattern: Optional[PatternAnalysis],
    logger
) -> List[dict]:
    """Deduplicate discovered entries that claim the same identifier."""
    if not pattern or not entries:
        return entries

    # Group by identifier
    by_id = {}
    for e in entries:
        ident = e.get("identifier", "")
        if ident not in by_id:
            by_id[ident] = []
        by_id[ident].append(e)

    # For each group with duplicates, pick best positional fit
    deduped = []
    body_start, body_end = pattern.body_range
    body_size = body_end - body_start

    for ident, candidates in by_id.items():
        if len(candidates) == 1:
            deduped.append(candidates[0])
        else:
            # Multiple candidates - pick best positional fit
            logger.info(f"Deduplicating identifier '{ident}': {len(candidates)} candidates")
            best = _pick_best_positional_fit(ident, candidates, pattern, body_start, body_size, logger)
            deduped.append(best)

    return deduped


def _pick_best_positional_fit(
    identifier: str,
    candidates: List[dict],
    pattern: PatternAnalysis,
    body_start: int,
    body_size: int,
    logger
) -> dict:
    """Pick the candidate with best positional fit for the identifier."""
    # Try to parse as integer
    try:
        num = int(identifier)
    except ValueError:
        # Non-numeric - pick first by page order
        candidates.sort(key=lambda e: e["scan_page"])
        logger.info(f"  Non-numeric '{identifier}', keeping first: p{candidates[0]['scan_page']}")
        return candidates[0]

    # Find matching sequential pattern
    for pat in pattern.discovered_patterns:
        if pat.pattern_type != "sequential":
            continue
        try:
            start = int(pat.range_start) if pat.range_start and pat.range_start.isdigit() else 1
            end = int(pat.range_end) if pat.range_end and pat.range_end.isdigit() else start

            if start <= num <= end:
                # Calculate expected page position
                total_entries = end - start + 1
                position_fraction = (num - start) / total_entries
                expected_page = body_start + int(position_fraction * body_size)

                # Pick candidate closest to expected position
                best = min(candidates, key=lambda e: abs(e["scan_page"] - expected_page))

                for c in candidates:
                    if c != best:
                        logger.info(f"  Rejecting p{c['scan_page']} (expected ~p{expected_page})")
                logger.info(f"  Keeping p{best['scan_page']} (closest to expected ~p{expected_page})")

                return best
        except (ValueError, TypeError):
            continue

    # No matching pattern - keep first by page order
    candidates.sort(key=lambda e: e["scan_page"])
    logger.info(f"  No pattern match for '{identifier}', keeping first: p{candidates[0]['scan_page']}")
    return candidates[0]


def _find_parent_toc_entry(scan_page: int, toc_entries: list, toc_index_map: dict):
    """Find the parent ToC entry for a discovered entry."""
    parent_entry = None
    parent_original_idx = None

    for i, entry in enumerate(toc_entries):
        if entry.scan_page and entry.scan_page <= scan_page:
            parent_entry = entry
            parent_original_idx = i
        elif entry.scan_page and entry.scan_page > scan_page:
            break

    if parent_entry and parent_original_idx is not None:
        enriched_idx = toc_index_map.get(parent_original_idx)
        return enriched_idx, parent_entry.level

    return None, 1
