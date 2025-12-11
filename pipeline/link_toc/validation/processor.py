"""Validation processor - checks page coverage and investigates gaps."""

import json
from typing import Dict, Any, List

from infra.llm.agent import AgentConfig, AgentBatchConfig, AgentBatchClient
from infra.pipeline.status import PhaseStatusTracker
from infra.config import Config

from ..schemas import (
    EnrichedToCEntry, EnrichedTableOfContents,
    LinkedToCEntry, LinkedTableOfContents,
    PatternAnalysis, PageGap, GapInvestigation, CoverageReport
)
from .coverage import find_gaps, compute_coverage_stats, is_back_matter_gap
from .agent import GapInvestigatorTools, INVESTIGATOR_SYSTEM_PROMPT, build_investigator_user_prompt


def validate_coverage(tracker: PhaseStatusTracker, **kwargs) -> Dict[str, Any]:
    """Main validation processor - find gaps and investigate them."""
    storage = tracker.storage
    logger = tracker.logger
    stage_storage = tracker.stage_storage
    model = kwargs.get("model") or Config.vision_model_primary

    # Load enriched ToC
    enriched_data = stage_storage.load_file("enriched_toc.json")
    if not enriched_data:
        logger.error("No enriched_toc.json found - cannot validate")
        return {}

    enriched_toc = EnrichedTableOfContents(**enriched_data)
    entries = [EnrichedToCEntry(**e) if isinstance(e, dict) else e for e in enriched_toc.entries]

    # Load pattern analysis for body_range
    pattern_data = stage_storage.load_file("pattern/pattern_analysis.json")
    if not pattern_data:
        logger.warning("No pattern analysis - using first/last entry as body range")
        if entries:
            body_range = (entries[0].scan_page, entries[-1].scan_page + 50)
        else:
            logger.error("No entries and no pattern - cannot validate")
            return {}
        pattern = None
    else:
        pattern = PatternAnalysis(**pattern_data)
        body_range = pattern.body_range

    # Load original ToC for cross-reference
    linked_data = stage_storage.load_file("linked_toc.json")
    if linked_data:
        linked_toc = LinkedTableOfContents(**linked_data)
        original_toc_entries = [e for e in linked_toc.entries if e is not None]
    else:
        original_toc_entries = []

    logger.info(f"Validating coverage: {len(entries)} entries, body range {body_range[0]}-{body_range[1]}")

    # Find gaps
    gaps = find_gaps(entries, body_range)
    logger.info(f"Found {len(gaps)} gaps in page coverage")

    if not gaps:
        # Perfect coverage
        covered, coverage_pct = compute_coverage_stats(entries, body_range)
        report = CoverageReport(
            body_range=body_range,
            total_body_pages=body_range[1] - body_range[0] + 1,
            entries_count=len(entries),
            gaps_found=0,
            gaps_fixed=0,
            gaps_no_fix_needed=0,
            gaps_flagged=0,
            pages_covered=covered,
            coverage_percent=coverage_pct,
            investigations=[],
            status="ok"
        )
        stage_storage.save_file("validation/coverage_report.json", report.model_dump())
        logger.info(f"Coverage validation complete: {coverage_pct:.1f}% coverage, no gaps")
        return {"status": "ok", "gaps": 0}

    # Filter out back matter gaps that are intentional
    gaps_to_investigate = []
    intentional_gaps = []

    for gap in gaps:
        if pattern and is_back_matter_gap(gap, pattern):
            intentional_gaps.append(gap)
            logger.info(f"Gap {gap.start_page}-{gap.end_page} is in excluded back matter - skipping")
        else:
            gaps_to_investigate.append(gap)

    logger.info(f"Investigating {len(gaps_to_investigate)} gaps ({len(intentional_gaps)} intentional)")

    # Investigate each gap with an agent
    investigations = []

    if gaps_to_investigate:
        investigations = _investigate_gaps(
            tracker=tracker,
            storage=storage,
            stage_storage=stage_storage,
            logger=logger,
            gaps=gaps_to_investigate,
            entries=entries,
            original_toc_entries=original_toc_entries,
            body_range=body_range,
            model=model,
        )

    # Add intentional gaps as no_fix_needed
    for gap in intentional_gaps:
        investigations.append(GapInvestigation(
            gap=gap,
            diagnosis="Gap is in excluded back matter (bibliography, index, etc.)",
            fix_type="no_fix_needed",
            fix_details=None,
            flagged_for_review=False,
        ))

    # Apply fixes to enriched_toc
    fixes_applied = _apply_fixes(stage_storage, entries, investigations, logger)

    # Compute final coverage
    updated_data = stage_storage.load_file("enriched_toc.json")
    updated_toc = EnrichedTableOfContents(**updated_data)
    updated_entries = [EnrichedToCEntry(**e) if isinstance(e, dict) else e for e in updated_toc.entries]

    covered, coverage_pct = compute_coverage_stats(updated_entries, body_range)

    # Count results
    gaps_fixed = sum(1 for inv in investigations if inv.fix_type in ("add_entry", "correct_entry"))
    gaps_no_fix = sum(1 for inv in investigations if inv.fix_type == "no_fix_needed")
    gaps_flagged = sum(1 for inv in investigations if inv.flagged_for_review)

    status = "ok" if gaps_flagged == 0 else "needs_review"
    if fixes_applied > 0:
        status = "fixed" if gaps_flagged == 0 else "needs_review"

    report = CoverageReport(
        body_range=body_range,
        total_body_pages=body_range[1] - body_range[0] + 1,
        entries_count=len(updated_entries),
        gaps_found=len(gaps),
        gaps_fixed=gaps_fixed,
        gaps_no_fix_needed=gaps_no_fix,
        gaps_flagged=gaps_flagged,
        pages_covered=covered,
        coverage_percent=coverage_pct,
        investigations=investigations,
        status=status
    )

    stage_storage.save_file("validation/coverage_report.json", report.model_dump())

    logger.info(f"Coverage validation complete: {coverage_pct:.1f}% coverage")
    logger.info(f"  Gaps: {len(gaps)} found, {gaps_fixed} fixed, {gaps_no_fix} no fix needed, {gaps_flagged} flagged")

    return {"status": status, "gaps": len(gaps), "fixed": gaps_fixed, "flagged": gaps_flagged}


def _investigate_gaps(
    tracker: PhaseStatusTracker,
    storage,
    stage_storage,
    logger,
    gaps: List[PageGap],
    entries: List[EnrichedToCEntry],
    original_toc_entries: List,
    body_range: tuple,
    model: str,
) -> List[GapInvestigation]:
    """Investigate gaps using agents."""

    configs = []
    tools_list = []

    for gap in gaps:
        agent_id = f"gap-{gap.start_page}-{gap.end_page}"

        tools = GapInvestigatorTools(
            storage=storage,
            gap=gap,
            enriched_entries=entries,
            original_toc_entries=original_toc_entries,
            body_range=body_range,
            logger=logger
        )
        tools_list.append(tools)

        initial_messages = [
            {"role": "system", "content": INVESTIGATOR_SYSTEM_PROMPT},
            {"role": "user", "content": build_investigator_user_prompt(gap, body_range)}
        ]

        configs.append(AgentConfig(
            model=model,
            initial_messages=initial_messages,
            tools=tools,
            tracker=tracker,
            agent_id=agent_id,
            max_iterations=20
        ))

    logger.info(f"Launching {len(configs)} gap investigation agents...")

    batch_config = AgentBatchConfig(
        tracker=tracker,
        agent_configs=configs,
        batch_name="gap-investigation",
        max_workers=min(len(configs), 5)  # Limit concurrency for vision calls
    )

    batch = AgentBatchClient(batch_config)
    batch_result = batch.run()

    investigations = []

    for agent_result, tools, gap in zip(batch_result.results, tools_list, gaps):
        result_data = tools.get_result()

        if result_data:
            inv = GapInvestigation(
                gap=gap,
                diagnosis=result_data.get("reasoning", "Agent completed without reasoning"),
                fix_type=result_data.get("fix_type"),
                fix_details=json.dumps(result_data.get("fix_details")) if result_data.get("fix_details") else None,
                flagged_for_review=result_data.get("flagged_for_review", False),
                flag_reason=result_data.get("reasoning") if result_data.get("flagged_for_review") else None,
            )
        else:
            inv = GapInvestigation(
                gap=gap,
                diagnosis="Agent did not complete investigation",
                fix_type="flagged",
                fix_details=None,
                flagged_for_review=True,
                flag_reason="Agent timed out or failed to produce a result",
            )

        investigations.append(inv)

        # Save individual investigation
        stage_storage.save_file(
            f"validation/gap_{gap.start_page}_{gap.end_page}.json",
            inv.model_dump()
        )

    return investigations


def _apply_fixes(
    stage_storage,
    entries: List[EnrichedToCEntry],
    investigations: List[GapInvestigation],
    logger
) -> int:
    """Apply fixes from investigations to the enriched ToC."""
    fixes_applied = 0

    for inv in investigations:
        if inv.fix_type == "add_entry" and inv.fix_details:
            details = json.loads(inv.fix_details)

            # Find max entry_index
            max_idx = max(e.entry_index for e in entries) if entries else -1

            new_entry = EnrichedToCEntry(
                entry_index=max_idx + 1,
                title=details["title"],
                scan_page=details["scan_page"],
                level=details["level"],
                parent_index=None,
                source="gap_fix",
                entry_number=details.get("entry_number"),
                discovery_reasoning=inv.diagnosis,
            )
            entries.append(new_entry)
            fixes_applied += 1
            logger.info(f"Added entry: {new_entry.title} at page {new_entry.scan_page}")

        elif inv.fix_type == "correct_entry" and inv.fix_details:
            details = json.loads(inv.fix_details)
            entry_idx = details["entry_index"]
            field = details["field"]
            new_value = details["new_value"]

            # Find entry by index
            for entry in entries:
                if entry.entry_index == entry_idx:
                    old_value = getattr(entry, field)
                    setattr(entry, field, new_value)
                    fixes_applied += 1
                    logger.info(f"Corrected entry {entry_idx}: {field} {old_value} -> {new_value}")
                    break

    if fixes_applied > 0:
        # Re-sort and re-index
        entries.sort(key=lambda e: e.scan_page)
        for i, entry in enumerate(entries):
            entry.entry_index = i

        # Save updated enriched ToC
        updated_toc = EnrichedTableOfContents(
            entries=entries,
            original_toc_count=sum(1 for e in entries if e.source == "toc"),
            discovered_count=sum(1 for e in entries if e.source in ("discovered", "missing_found", "gap_fix")),
            total_entries=len(entries),
        )
        stage_storage.save_file("enriched_toc.json", updated_toc.model_dump())
        logger.info(f"Applied {fixes_applied} fixes to enriched_toc.json")

    return fixes_applied
