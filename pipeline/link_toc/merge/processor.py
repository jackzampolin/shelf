from ..schemas import LinkedTableOfContents, PatternAnalysis, HeadingDecision
from ..schemas import EnrichedToCEntry, EnrichedTableOfContents


def find_parent_toc_entry(scan_page: int, toc_entries: list, toc_index_map: dict):
    """Find the parent ToC entry for a discovered heading based on page range.

    Returns (parent_index, parent_level) or (None, 1) if no parent found.
    """
    # Find the ToC entry that precedes this page (parent container)
    parent_entry = None
    parent_original_idx = None

    for i, entry in enumerate(toc_entries):
        if entry.scan_page and entry.scan_page <= scan_page:
            parent_entry = entry
            parent_original_idx = i
        elif entry.scan_page and entry.scan_page > scan_page:
            break

    if parent_entry and parent_original_idx is not None:
        # Get the enriched index for this parent
        enriched_idx = toc_index_map.get(parent_original_idx)
        return enriched_idx, parent_entry.level

    return None, 1


def merge_enriched_toc(tracker, **kwargs):
    storage = tracker.storage
    logger = tracker.logger
    stage_storage = tracker.stage_storage

    linked_toc_data = stage_storage.load_file("linked_toc.json")
    if not linked_toc_data:
        logger.warning("No linked_toc.json - cannot merge")
        return

    linked_toc = LinkedTableOfContents(**linked_toc_data)

    pattern_data = storage.stage("link-toc").load_file("pattern/pattern_analysis.json")
    if not pattern_data:
        logger.info("No pattern analysis - using ToC only")
        pattern = None
    else:
        pattern = PatternAnalysis(**pattern_data)

    eval_dir = stage_storage.output_dir / "evaluation"
    approved_headings = []
    missing_headings_found = []

    if eval_dir.exists():
        # Load approved candidate headings
        for decision_file in sorted(eval_dir.glob("heading_*.json")):
            decision_data = storage.stage("link-toc").load_file(f"evaluation/{decision_file.name}")
            if decision_data:
                decision = HeadingDecision(**decision_data)
                if decision.include:
                    approved_headings.append(decision)

        # Load found missing headings (predicted headings that were located)
        for decision_file in sorted(eval_dir.glob("missing_*.json")):
            decision_data = storage.stage("link-toc").load_file(f"evaluation/{decision_file.name}")
            if decision_data:
                decision = HeadingDecision(**decision_data)
                if decision.include:
                    missing_headings_found.append(decision)

    total_discovered = len(approved_headings) + len(missing_headings_found)
    logger.info(f"Merging {len(linked_toc.entries)} ToC entries + {total_discovered} discovered headings")
    if missing_headings_found:
        logger.info(f"  ({len(approved_headings)} from candidates, {len(missing_headings_found)} from missing search)")

    enriched_entries = []
    entry_index = 0

    toc_entries = [e for e in linked_toc.entries if e is not None]

    # Validate: Filter out entries without scan_page
    valid_toc_entries = []
    invalid_toc_entries = []

    for toc_entry in toc_entries:
        if toc_entry.scan_page is None:
            invalid_toc_entries.append(toc_entry)
            logger.warning(
                f"Skipping ToC entry '{toc_entry.title}' - no scan_page found (agent reasoning: {toc_entry.agent_reasoning})"
            )
        else:
            valid_toc_entries.append(toc_entry)

    if invalid_toc_entries:
        logger.error(
            f"IMPORTANT: {len(invalid_toc_entries)}/{len(toc_entries)} ToC entries could not be linked to scan pages. "
            f"These entries will be EXCLUDED from the enriched ToC. Unlinked entries: {[e.title for e in invalid_toc_entries]}"
        )

    # Build map from original ToC index to enriched index
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

    # Add discovered headings (from candidate evaluation) with proper parent relationships
    for heading in approved_headings:
        parent_idx, parent_level = find_parent_toc_entry(
            heading.scan_page,
            valid_toc_entries,
            toc_index_map
        )

        # Discovered headings are children of their parent ToC entry
        # Level = parent_level + 1 (one level below the parent)
        child_level = parent_level + 1

        enriched_entries.append(EnrichedToCEntry(
            entry_index=entry_index,
            title=heading.title or heading.heading_text,
            scan_page=heading.scan_page,
            level=child_level,
            parent_index=parent_idx,
            source="discovered",
            entry_number=heading.entry_number,
            discovery_reasoning=heading.reasoning,
            label_structure_level=None
        ))
        entry_index += 1

    # Add missing headings (predicted chapters that were found)
    # These are typically top-level entries that weren't in the original ToC
    for heading in missing_headings_found:
        # Missing headings are usually chapters, so use level 1 (or the level from the decision)
        heading_level = heading.level if heading.level else 1

        enriched_entries.append(EnrichedToCEntry(
            entry_index=entry_index,
            title=heading.title or heading.heading_text,
            scan_page=heading.scan_page,
            level=heading_level,
            parent_index=None,  # Top-level missing chapters don't have parents
            source="missing_found",
            entry_number=heading.entry_number,
            discovery_reasoning=heading.reasoning,
            label_structure_level=None
        ))
        entry_index += 1

    # Sort by page number
    enriched_entries.sort(key=lambda e: e.scan_page)

    for i, entry in enumerate(enriched_entries):
        entry.entry_index = i

    enriched_toc = EnrichedTableOfContents(
        entries=enriched_entries,
        original_toc_count=len(valid_toc_entries),
        discovered_count=total_discovered,
        total_entries=len(enriched_entries),
        pattern_confidence=pattern.confidence if pattern else 0.0,
        pattern_description=pattern.pattern_description if pattern else "No pattern analysis"
    )

    stage_storage.save_file("enriched_toc.json", enriched_toc.model_dump())

    logger.info(f"Enriched ToC created: {len(enriched_entries)} total entries")
    logger.info(f"  Original ToC: {len(valid_toc_entries)}")
    logger.info(f"  Discovered: {len(approved_headings)}")
    if missing_headings_found:
        logger.info(f"  Missing found: {len(missing_headings_found)}")
