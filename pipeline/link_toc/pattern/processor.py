import bisect

from infra.llm.single import LLMSingleCall, LLMSingleCallConfig
from infra.config import Config
from ..schemas import (
    LinkedTableOfContents,
    PatternAnalysis,
    CandidateHeading,
    DiscoveredPattern,
    ExcludedPageRange,
)
from .prompts import PATTERN_SYSTEM_PROMPT, build_pattern_prompt


def analyze_toc_pattern(tracker, **kwargs):
    """Analyze ToC and candidate headings to identify patterns for discovery.

    Outputs:
    - discovered_patterns: Sequential patterns (chapters 1-38) to search for
    - excluded_page_ranges: Back matter sections to skip
    """
    storage = tracker.storage
    logger = tracker.logger
    stage_storage = tracker.stage_storage
    model = kwargs.get('model') or Config.vision_model_primary

    linked_toc_data = stage_storage.load_file("linked_toc.json")
    if not linked_toc_data:
        logger.warning("No linked_toc.json found - skipping pattern analysis")
        return

    linked_toc = LinkedTableOfContents(**linked_toc_data)
    if not linked_toc.entries:
        logger.info("No ToC entries - skipping pattern analysis")
        return

    toc_entries = [e for e in linked_toc.entries if e is not None]
    toc_pages = [e.scan_page for e in toc_entries if e.scan_page]
    if not toc_pages:
        logger.warning("No ToC entries with scan_pages - skipping")
        return

    # Load candidate headings from label-structure
    all_headings = _load_all_headings(storage, logger)

    body_range = (min(toc_pages), max(toc_pages))
    toc_entries_by_page = {e.scan_page: e for e in toc_entries if e.scan_page}

    # Build candidates (headings not already in ToC)
    candidate_headings = _build_candidates(all_headings, body_range, toc_pages, toc_entries_by_page)
    logger.info(f"ToC: {len(toc_pages)} pages, Candidates: {len(candidate_headings)} headings in body")

    # Call LLM to identify patterns
    patterns, excluded, reasoning = _analyze_with_llm(
        tracker, model, logger, toc_entries, candidate_headings, body_range
    )

    # Save simplified output
    pattern_analysis = PatternAnalysis(
        body_range=body_range,
        candidate_headings=[],  # No longer storing candidates
        discovered_patterns=patterns,
        excluded_page_ranges=excluded,
        requires_evaluation=False,  # Deprecated - discover phase handles this
        reasoning=reasoning
    )

    storage.stage("link-toc").save_file(
        "pattern/pattern_analysis.json",
        pattern_analysis.model_dump(),
        schema=PatternAnalysis
    )

    # Log summary
    for p in patterns:
        if p.pattern_type == "sequential":
            logger.info(f"Pattern: {p.level_name} {p.range_start}-{p.range_end} (level {p.level})")
    if excluded:
        logger.info(f"Excluded ranges: {len(excluded)}")


def _load_all_headings(storage, logger):
    """Load headings from label-structure mechanical output."""
    mechanical_dir = storage.stage("label-structure").output_dir / "mechanical"
    if not mechanical_dir.exists():
        logger.warning("label-structure mechanical output not found")
        return []

    all_headings = []
    for page_file in sorted(mechanical_dir.glob("page_*.json")):
        page_data = storage.stage("label-structure").load_file(f"mechanical/{page_file.name}")
        if not page_data:
            continue

        page_num = int(page_file.stem.split("_")[1])
        for heading in page_data.get("headings", []):
            all_headings.append({
                "scan_page": page_num,
                "text": heading.get("text", ""),
                "level": heading.get("level", 1)
            })

    logger.info(f"Found {len(all_headings)} headings in label-structure")
    return all_headings


def _build_candidates(all_headings, body_range, toc_pages, toc_entries_by_page):
    """Build candidate headings that are NOT already in ToC."""
    candidates = []
    for h in all_headings:
        page = h["scan_page"]
        if not (body_range[0] <= page <= body_range[1]):
            continue

        toc_entry = toc_entries_by_page.get(page)
        if toc_entry and _matches_toc_entry(h["text"], toc_entry):
            continue

        idx = bisect.bisect_left(toc_pages, page)
        preceding = toc_pages[idx - 1] if idx > 0 else None
        if idx < len(toc_pages) and toc_pages[idx] == page:
            following = toc_pages[idx + 1] if idx + 1 < len(toc_pages) else None
        else:
            following = toc_pages[idx] if idx < len(toc_pages) else None

        candidates.append(CandidateHeading(
            scan_page=page,
            heading_text=h["text"],
            heading_level=h["level"],
            preceding_toc_page=preceding,
            following_toc_page=following,
        ))

    return candidates


def _matches_toc_entry(heading_text, entry):
    """Check if heading matches an existing ToC entry."""
    text = heading_text.lower().strip()
    if entry.title and text == entry.title.lower().strip():
        return True
    if entry.entry_number:
        num = entry.entry_number.lower().strip()
        level = (entry.level_name or "").lower()
        if text == num or text == f"{level} {num}":
            return True
    return False


def _analyze_with_llm(tracker, model, logger, toc_entries, candidate_headings, body_range):
    """Call LLM to identify patterns and excluded ranges."""
    if not candidate_headings:
        logger.info("No candidates to analyze - checking ToC for excluded ranges only")

    logger.info(f"Calling LLM to analyze patterns...")

    llm = LLMSingleCall(LLMSingleCallConfig(
        tracker=tracker,
        model=model,
        call_name="pattern",
        metric_key="pattern_llm"
    ))

    result = llm.call(
        messages=[
            {"role": "system", "content": PATTERN_SYSTEM_PROMPT},
            {"role": "user", "content": build_pattern_prompt(toc_entries, candidate_headings, body_range)}
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "pattern_analysis",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "discovered_patterns": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "pattern_type": {"type": "string", "enum": ["sequential", "named"]},
                                    "level_name": {"type": ["string", "null"]},
                                    "range_start": {"type": ["string", "null"]},
                                    "range_end": {"type": ["string", "null"]},
                                    "level": {"type": ["integer", "null"]},
                                    "reasoning": {"type": "string"}
                                },
                                "required": ["pattern_type", "reasoning"],
                                "additionalProperties": False
                            }
                        },
                        "excluded_page_ranges": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "start_page": {"type": "integer"},
                                    "end_page": {"type": "integer"},
                                    "reason": {"type": "string"}
                                },
                                "required": ["start_page", "end_page", "reason"],
                                "additionalProperties": False
                            }
                        },
                        "reasoning": {"type": "string"}
                    },
                    "required": ["discovered_patterns", "excluded_page_ranges", "reasoning"],
                    "additionalProperties": False
                }
            }
        },
        max_tokens=2000,
    )

    if not result.success or not result.parsed_json:
        logger.warning(f"Pattern analysis failed: {result.error_message}")
        return [], [], f"LLM call failed: {result.error_message}"

    data = result.parsed_json
    reasoning = data.get("reasoning", "")

    # Parse patterns (simplified - no more missing_entries)
    patterns = []
    for p in data.get("discovered_patterns", []):
        try:
            patterns.append(DiscoveredPattern(
                pattern_type=p["pattern_type"],
                level_name=p.get("level_name"),
                range_start=p.get("range_start"),
                range_end=p.get("range_end"),
                level=p.get("level"),
                action="include",  # All discovered patterns are include
                confidence=None,  # Will be calculated after discovery
                missing_entries=[],  # Not used anymore
                reasoning=p.get("reasoning", "")
            ))
        except (KeyError, TypeError) as e:
            logger.warning(f"Failed to parse pattern: {e}")

    # Parse excluded ranges
    excluded = []
    for ex in data.get("excluded_page_ranges", []):
        try:
            excluded.append(ExcludedPageRange(
                start_page=ex["start_page"],
                end_page=ex["end_page"],
                reason=ex.get("reason", "")
            ))
        except (KeyError, TypeError):
            pass

    logger.info(f"LLM identified {len(patterns)} patterns, {len(excluded)} excluded ranges")
    return patterns, excluded, reasoning
