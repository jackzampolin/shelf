"""Discover phase: Launch agents to find each entry in detected patterns."""

import re
from typing import List, Tuple, Optional

from infra.llm.agent import AgentConfig, AgentBatchConfig, AgentBatchClient
from infra.config import Config
from infra.pipeline.status import PhaseStatusTracker

from ..schemas import PatternAnalysis, DiscoveredPattern, ExcludedPageRange
from .tools import PatternEntryFinderTools
from .prompts import FINDER_SYSTEM_PROMPT, build_finder_user_prompt


def discover_pattern_entries(tracker: PhaseStatusTracker, model: str = None, **kwargs):
    """Launch agents to find each entry in detected sequential patterns."""
    storage = tracker.storage
    logger = tracker.logger
    stage_storage = tracker.stage_storage

    model = model or Config.vision_model_primary

    # Load pattern analysis
    pattern_data = stage_storage.load_file("pattern/pattern_analysis.json")
    if not pattern_data:
        logger.info("No pattern analysis found - skipping discovery")
        return

    pattern = PatternAnalysis(**pattern_data)

    # Get sequential patterns to search
    sequential_patterns = [
        p for p in pattern.discovered_patterns
        if p.pattern_type == "sequential" and p.range_start and p.range_end
    ]

    if not sequential_patterns:
        logger.info("No sequential patterns to discover")
        # Save empty completion marker
        stage_storage.save_file("discover/discover_complete.json", {
            "total_entries": 0,
            "searched": 0,
            "found": 0,
            "not_found": 0,
        })
        return

    # Generate all entries to find
    entries_to_find = []
    for p in sequential_patterns:
        entries = _generate_pattern_entries(p, pattern.body_range, logger)
        entries_to_find.extend(entries)

    if not entries_to_find:
        logger.info("No entries to discover")
        stage_storage.save_file("discover/discover_complete.json", {
            "total_entries": 0,
            "searched": 0,
            "found": 0,
            "not_found": 0,
        })
        return

    # Check what's already been found
    discover_dir = stage_storage.output_dir / "discover"
    discover_dir.mkdir(parents=True, exist_ok=True)

    entries_to_search = []
    for entry in entries_to_find:
        result_file = discover_dir / f"{entry['file_key']}.json"
        if result_file.exists():
            continue
        entries_to_search.append(entry)

    if not entries_to_search:
        logger.info(f"All {len(entries_to_find)} entries already discovered")
        return

    logger.info(f"Discovering {len(entries_to_search)}/{len(entries_to_find)} pattern entries...")

    # Get book metadata
    total_pages = storage.load_metadata().get('total_pages', 0)

    # Build agent configs
    configs = []
    tools_list = []

    for entry in entries_to_search:
        agent_id = f"find-{entry['file_key']}"

        tools = PatternEntryFinderTools(
            storage=storage,
            entry=entry,
            excluded_ranges=pattern.excluded_page_ranges,
            total_pages=total_pages,
            logger=logger
        )
        tools_list.append(tools)

        configs.append(AgentConfig(
            model=model,
            initial_messages=[
                {"role": "system", "content": FINDER_SYSTEM_PROMPT},
                {"role": "user", "content": build_finder_user_prompt(entry, total_pages)}
            ],
            tools=tools,
            tracker=tracker,
            agent_id=agent_id,
            max_iterations=15
        ))

    # Run agents in parallel
    batch_config = AgentBatchConfig(
        tracker=tracker,
        agent_configs=configs,
        batch_name="discover",
        max_workers=10
    )

    batch = AgentBatchClient(batch_config)
    batch_result = batch.run()

    # Process results
    found_count = 0
    not_found_count = 0

    for agent_result, tools, entry in zip(batch_result.results, tools_list, entries_to_search):
        result_data = tools._pending_result

        if result_data and result_data.get("scan_page"):
            # Found - construct title from heading_format if available
            # heading_format uses {n} placeholder: "CHAPTER {n}" -> "CHAPTER 1"
            identifier = entry["identifier"]
            heading_format = entry.get("heading_format")
            level_name = entry.get("level_name", "")

            if heading_format:
                # Use detected format from pattern phase
                title = heading_format.replace("{n}", identifier)
            elif level_name:
                # Fallback: capitalize level_name
                title = f"{level_name.capitalize()} {identifier}"
            else:
                title = identifier

            discovery_result = {
                "identifier": identifier,
                "level_name": level_name,
                "level": entry["level"],
                "scan_page": result_data["scan_page"],
                "title": title,
                "reasoning": result_data.get("reasoning", ""),
                "found": True,
            }
            found_count += 1
        else:
            # Not found
            reason = result_data.get("reasoning", "Agent did not complete") if result_data else "Agent failed"
            discovery_result = {
                "identifier": entry["identifier"],
                "level_name": entry["level_name"],
                "level": entry["level"],
                "scan_page": None,
                "reasoning": reason,
                "found": False,
            }
            not_found_count += 1

        # Save result
        stage_storage.save_file(f"discover/{entry['file_key']}.json", discovery_result)

    logger.info(f"Discovery complete: {found_count} found, {not_found_count} not found")

    # Save completion marker
    stage_storage.save_file("discover/discover_complete.json", {
        "total_entries": len(entries_to_find),
        "searched": len(entries_to_search),
        "found": found_count,
        "not_found": not_found_count,
    })


def _generate_pattern_entries(
    pattern: DiscoveredPattern,
    body_range: Tuple[int, int],
    logger
) -> List[dict]:
    """Generate list of entries to find for a sequential pattern."""
    entries = []

    level_name = pattern.level_name or "entry"
    level = pattern.level or 2
    heading_format = pattern.heading_format  # e.g., "CHAPTER {n}", "{n}"

    # Parse range
    start = pattern.range_start
    end = pattern.range_end

    # Try numeric range
    if start.isdigit() and end.isdigit():
        start_num = int(start)
        end_num = int(end)
        count = end_num - start_num + 1

        # Calculate expected page range per entry
        body_pages = body_range[1] - body_range[0]
        pages_per_entry = body_pages // count if count > 0 else 50

        for i in range(start_num, end_num + 1):
            # Estimate where this entry should be
            entry_offset = (i - start_num) * pages_per_entry
            predicted_start = body_range[0] + entry_offset
            predicted_end = min(predicted_start + pages_per_entry + 20, body_range[1])
            predicted_start = max(predicted_start - 10, body_range[0])

            entries.append({
                "identifier": str(i),
                "level_name": level_name,
                "level": level,
                "heading_format": heading_format,
                "search_range": (predicted_start, predicted_end),
                "file_key": f"{level_name}_{i:03d}",
            })

        logger.info(f"Generated {len(entries)} entries for {level_name} {start}-{end}")

    # Try Roman numeral range
    elif _is_roman(start) and _is_roman(end):
        start_num = _roman_to_int(start)
        end_num = _roman_to_int(end)

        body_pages = body_range[1] - body_range[0]
        count = end_num - start_num + 1
        pages_per_entry = body_pages // count if count > 0 else 50

        for i in range(start_num, end_num + 1):
            roman = _int_to_roman(i)
            entry_offset = (i - start_num) * pages_per_entry
            predicted_start = body_range[0] + entry_offset
            predicted_end = min(predicted_start + pages_per_entry + 20, body_range[1])
            predicted_start = max(predicted_start - 10, body_range[0])

            entries.append({
                "identifier": roman,
                "level_name": level_name,
                "level": level,
                "heading_format": heading_format,
                "search_range": (predicted_start, predicted_end),
                "file_key": f"{level_name}_{i:03d}",
            })

        logger.info(f"Generated {len(entries)} entries for {level_name} {start}-{end}")

    # Try letter range (A-F)
    elif len(start) == 1 and len(end) == 1 and start.isalpha() and end.isalpha():
        start_ord = ord(start.upper())
        end_ord = ord(end.upper())

        body_pages = body_range[1] - body_range[0]
        count = end_ord - start_ord + 1
        pages_per_entry = body_pages // count if count > 0 else 50

        for i in range(start_ord, end_ord + 1):
            letter = chr(i)
            entry_offset = (i - start_ord) * pages_per_entry
            predicted_start = body_range[0] + entry_offset
            predicted_end = min(predicted_start + pages_per_entry + 20, body_range[1])
            predicted_start = max(predicted_start - 10, body_range[0])

            entries.append({
                "identifier": letter,
                "level_name": level_name,
                "level": level,
                "heading_format": heading_format,
                "search_range": (predicted_start, predicted_end),
                "file_key": f"{level_name}_{letter}",
            })

        logger.info(f"Generated {len(entries)} entries for {level_name} {start}-{end}")

    else:
        logger.warning(f"Could not parse range {start}-{end} for {level_name}")

    return entries


def _is_roman(s: str) -> bool:
    """Check if string is a valid Roman numeral."""
    return bool(re.match(r'^[IVXLCDM]+$', s.upper()))


def _roman_to_int(s: str) -> int:
    """Convert Roman numeral to integer."""
    roman_values = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}
    s = s.upper()
    total = 0
    prev = 0
    for c in reversed(s):
        val = roman_values.get(c, 0)
        if val < prev:
            total -= val
        else:
            total += val
        prev = val
    return total


def _int_to_roman(num: int) -> str:
    """Convert integer to Roman numeral."""
    val = [1000, 900, 500, 400, 100, 90, 50, 40, 10, 9, 5, 4, 1]
    syms = ['M', 'CM', 'D', 'CD', 'C', 'XC', 'L', 'XL', 'X', 'IX', 'V', 'IV', 'I']
    roman = ''
    for i, v in enumerate(val):
        while num >= v:
            roman += syms[i]
            num -= v
    return roman
