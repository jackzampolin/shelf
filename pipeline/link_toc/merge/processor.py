from ..schemas import LinkedTableOfContents, PatternAnalysis, HeadingDecision
from ..schemas import EnrichedToCEntry, EnrichedTableOfContents


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

    if eval_dir.exists():
        for decision_file in sorted(eval_dir.glob("heading_*.json")):
            decision_data = storage.stage("link-toc").load_file(f"evaluation/{decision_file.name}")
            if decision_data:
                decision = HeadingDecision(**decision_data)
                if decision.include:
                    approved_headings.append(decision)

    logger.info(f"Merging {len(linked_toc.entries)} ToC entries + {len(approved_headings)} discovered headings")

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

    for toc_entry in valid_toc_entries:
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

    for heading in approved_headings:
        enriched_entries.append(EnrichedToCEntry(
            entry_index=entry_index,
            title=heading.title or heading.heading_text,
            scan_page=heading.scan_page,
            level=heading.level or 2,  # Default to level 2: ToC entries are typically level 1 chapters, discovered headings fill gaps as sections
            parent_index=heading.parent_toc_entry_index,
            source="discovered",
            discovery_reasoning=heading.reasoning,
            label_structure_level=None
        ))
        entry_index += 1

    enriched_entries.sort(key=lambda e: e.scan_page)

    for i, entry in enumerate(enriched_entries):
        entry.entry_index = i

    enriched_toc = EnrichedTableOfContents(
        entries=enriched_entries,
        original_toc_count=len(valid_toc_entries),
        discovered_count=len(approved_headings),
        total_entries=len(enriched_entries),
        pattern_confidence=pattern.confidence if pattern else 0.0,
        pattern_description=pattern.pattern_description if pattern else "No pattern analysis"
    )

    stage_storage.save_file("enriched_toc.json", enriched_toc.model_dump())

    logger.info(f"Enriched ToC created: {len(enriched_entries)} total entries")
    logger.info(f"  Original ToC: {len(valid_toc_entries)}")
    logger.info(f"  Discovered: {len(approved_headings)}")
