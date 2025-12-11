from typing import List, Optional
from ..schemas import LinkedTableOfContents, PatternAnalysis, HeadingDecision
from ..schemas import EnrichedToCEntry, EnrichedTableOfContents


def _deduplicate_by_entry_number(
    headings: List[HeadingDecision],
    pattern: Optional[PatternAnalysis],
    logger
) -> List[HeadingDecision]:
    """
    Deduplicate headings that claim the same entry_number.

    For sequential patterns (chapters 1-38), each number should appear only once.
    When duplicates exist, keep the one with better positional fit.
    """
    if not pattern or not headings:
        return headings

    # Group headings by entry_number
    by_number = {}
    no_number = []

    for h in headings:
        if h.entry_number:
            if h.entry_number not in by_number:
                by_number[h.entry_number] = []
            by_number[h.entry_number].append(h)
        else:
            no_number.append(h)

    # For each group with duplicates, pick the best one
    deduped = []
    body_start, body_end = pattern.body_range
    body_size = body_end - body_start

    # Find sequential include patterns to determine expected positions
    sequential_patterns = [
        p for p in pattern.discovered_patterns
        if p.pattern_type == "sequential" and p.action == "include"
    ]

    for entry_num, candidates in by_number.items():
        if len(candidates) == 1:
            deduped.append(candidates[0])
        else:
            # Multiple candidates for same entry_number - pick best positional fit
            logger.info(f"Deduplicating entry_number '{entry_num}': {len(candidates)} candidates")

            # Try to determine expected position from pattern
            best = _pick_best_positional_fit(
                entry_num, candidates, sequential_patterns, body_start, body_size, logger
            )
            deduped.append(best)

    # Add headings without entry_number
    deduped.extend(no_number)

    return deduped


def _pick_best_positional_fit(
    entry_num: str,
    candidates: List[HeadingDecision],
    sequential_patterns: list,
    body_start: int,
    body_size: int,
    logger
) -> HeadingDecision:
    """Pick the candidate with best positional fit for the entry number."""

    # Try to parse entry_num as integer for position calculation
    try:
        num = int(entry_num)
    except ValueError:
        # Non-numeric entry_number - just pick first by page order
        candidates.sort(key=lambda h: h.scan_page)
        logger.info(f"  Non-numeric '{entry_num}', keeping first: p{candidates[0].scan_page}")
        return candidates[0]

    # Find the pattern this number belongs to
    for pat in sequential_patterns:
        try:
            start = int(pat.range_start) if pat.range_start and pat.range_start.isdigit() else 1
            end = int(pat.range_end) if pat.range_end and pat.range_end.isdigit() else start

            if start <= num <= end:
                # Calculate expected page position
                total_entries = end - start + 1
                position_fraction = (num - start) / total_entries
                expected_page = body_start + int(position_fraction * body_size)

                # Pick candidate closest to expected position
                best = min(candidates, key=lambda h: abs(h.scan_page - expected_page))

                for c in candidates:
                    if c != best:
                        logger.info(f"  Rejecting p{c.scan_page} '{c.title}' (expected ~p{expected_page})")
                logger.info(f"  Keeping p{best.scan_page} '{best.title}' (closest to expected ~p{expected_page})")

                return best
        except (ValueError, TypeError):
            continue

    # No matching pattern found - keep first by page order
    candidates.sort(key=lambda h: h.scan_page)
    logger.info(f"  No pattern match for '{entry_num}', keeping first: p{candidates[0].scan_page}")
    return candidates[0]


def find_parent_toc_entry(scan_page: int, toc_entries: list, toc_index_map: dict):
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
        for decision_file in sorted(eval_dir.glob("heading_*.json")):
            decision_data = storage.stage("link-toc").load_file(f"evaluation/{decision_file.name}")
            if decision_data:
                decision = HeadingDecision(**decision_data)
                if decision.include:
                    approved_headings.append(decision)

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

    # Build set of pages that already have ToC entries - NEVER add duplicates
    toc_pages = {e.scan_page for e in valid_toc_entries}

    # Deduplicate by entry_number - if multiple headings claim the same number,
    # keep the one with the best positional fit for sequential patterns
    approved_headings = _deduplicate_by_entry_number(approved_headings, pattern, logger)

    skipped_duplicates = 0
    for heading in approved_headings:
        # CRITICAL: Never add a discovered heading for a page that already has a ToC entry
        if heading.scan_page in toc_pages:
            logger.info(f"Skipping duplicate: '{heading.title}' on page {heading.scan_page} (ToC already has entry)")
            skipped_duplicates += 1
            continue

        parent_idx, parent_level = find_parent_toc_entry(
            heading.scan_page,
            valid_toc_entries,
            toc_index_map
        )

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

    if skipped_duplicates:
        logger.warning(f"Skipped {skipped_duplicates} discovered headings that duplicated ToC pages")

    for heading in missing_headings_found:
        # Also check missing_found for duplicates
        if heading.scan_page in toc_pages:
            logger.info(f"Skipping duplicate missing: '{heading.title}' on page {heading.scan_page} (ToC already has entry)")
            skipped_duplicates += 1
            continue

        heading_level = heading.level if heading.level else 1

        enriched_entries.append(EnrichedToCEntry(
            entry_index=entry_index,
            title=heading.title or heading.heading_text,
            scan_page=heading.scan_page,
            level=heading_level,
            parent_index=None,
            source="missing_found",
            entry_number=heading.entry_number,
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
        discovered_count=total_discovered,
        total_entries=len(enriched_entries),
    )

    stage_storage.save_file("enriched_toc.json", enriched_toc.model_dump())

    logger.info(f"Enriched ToC created: {len(enriched_entries)} total entries")
    logger.info(f"  Original ToC: {len(valid_toc_entries)}")
    logger.info(f"  Discovered: {len(approved_headings)}")
    if missing_headings_found:
        logger.info(f"  Missing found: {len(missing_headings_found)}")
