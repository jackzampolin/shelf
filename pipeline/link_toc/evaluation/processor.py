import json
from typing import Dict, Any, Optional, Tuple, List

from infra.llm.batch import LLMBatchProcessor, LLMBatchConfig
from infra.llm.agent import AgentConfig, AgentBatchConfig, AgentBatchClient
from infra.pipeline.status import PhaseStatusTracker
from infra.config import Config

from ..schemas import PatternAnalysis, HeadingDecision, MissingEntry, DiscoveredPattern
from .request_builder import prepare_evaluation_request
from .result_handler import create_evaluation_handler
from .agent import MissingHeadingSearchTools, SEARCHER_SYSTEM_PROMPT, build_searcher_user_prompt


def _extract_missing_entries(patterns: List[DiscoveredPattern], body_range: Tuple[int, int]) -> List[MissingEntry]:
    """Extract all missing entries from discovered patterns, enriched with parent context."""
    missing = []
    body_pages = body_range[1] - body_range[0] + 1

    for pattern in patterns:
        if pattern.pattern_type == "sequential" and pattern.action == "include":
            # Calculate pattern stats
            pattern_desc = f"{pattern.level_name or 'entries'} {pattern.range_start}-{pattern.range_end}"

            # Estimate expected count from range
            try:
                start = int(pattern.range_start) if pattern.range_start.isdigit() else 1
                end = int(pattern.range_end) if pattern.range_end.isdigit() else start
                expected = end - start + 1
            except (ValueError, AttributeError):
                expected = None

            # Found count from confidence
            found = None
            if pattern.confidence and expected:
                found = int(pattern.confidence * expected)

            # Avg pages per entry
            avg_pages = body_pages // expected if expected else None

            for entry in pattern.missing_entries:
                enriched = MissingEntry(
                    identifier=entry.identifier,
                    predicted_page_range=entry.predicted_page_range,
                    level_name=entry.level_name or pattern.level_name,
                    level=entry.level or pattern.level,
                    pattern_description=pattern_desc,
                    pattern_found=found,
                    pattern_expected=expected,
                    avg_pages_per_entry=avg_pages,
                )
                missing.append(enriched)
    return missing


def is_in_excluded_range(page_num: int, excluded_ranges: list) -> bool:
    for ex_range in excluded_ranges:
        if ex_range.start_page <= page_num <= ex_range.end_page:
            return True
    return False


def _get_excluded_pages_for_candidate(
    missing: MissingEntry,
    excluded_ranges: list,
    stage_storage
) -> List[int]:
    excluded = []
    start_page, end_page = missing.predicted_page_range

    for page_num in range(start_page, end_page + 1):
        if is_in_excluded_range(page_num, excluded_ranges):
            excluded.append(page_num)
        existing_eval = stage_storage.output_dir / "evaluation" / f"heading_{page_num:04d}.json"
        if existing_eval.exists():
            excluded.append(page_num)

    return excluded


def search_missing_candidates(
    tracker: PhaseStatusTracker,
    pattern: PatternAnalysis,
    model: str,
) -> int:
    storage = tracker.storage
    logger = tracker.logger
    stage_storage = tracker.stage_storage

    missing_candidates = _extract_missing_entries(pattern.discovered_patterns, pattern.body_range)
    if not missing_candidates:
        return 0

    candidates_to_search = []
    for missing in missing_candidates:
        found_file = stage_storage.output_dir / "evaluation" / f"missing_{missing.identifier.replace(' ', '_')}.json"
        if not found_file.exists():
            candidates_to_search.append(missing)

    if not candidates_to_search:
        logger.info("Missing candidate search: all already processed")
        return 0

    logger.info(f"Searching for {len(candidates_to_search)} missing heading candidates...")

    configs = []
    tools_list = []

    for missing in candidates_to_search:
        agent_id = f"search-{missing.identifier.replace(' ', '-')}"

        excluded_pages = _get_excluded_pages_for_candidate(
            missing, pattern.excluded_page_ranges, stage_storage
        )

        tools = MissingHeadingSearchTools(
            storage=storage,
            missing_candidate=missing,
            excluded_pages=excluded_pages,
            logger=logger
        )
        tools_list.append(tools)

        initial_messages = [
            {"role": "system", "content": SEARCHER_SYSTEM_PROMPT},
            {"role": "user", "content": build_searcher_user_prompt(missing, excluded_pages)}
        ]

        configs.append(AgentConfig(
            model=model,
            initial_messages=initial_messages,
            tools=tools,
            tracker=tracker,
            agent_id=agent_id,
            max_iterations=15
        ))

    batch_config = AgentBatchConfig(
        tracker=tracker,
        agent_configs=configs,
        batch_name="missing-search",
        max_workers=len(configs)
    )

    batch = AgentBatchClient(batch_config)
    batch_result = batch.run()

    found_count = 0

    for agent_result, tools, missing in zip(batch_result.results, tools_list, candidates_to_search):
        result_data = tools._pending_result

        # Build title from pattern context (e.g., "Chapter 9" not raw OCR)
        if missing.level_name:
            title = f"{missing.level_name.title()} {missing.identifier}"
        else:
            title = missing.identifier
        level = missing.level or 1

        if result_data and result_data.get("found") and result_data.get("scan_page"):
            decision = HeadingDecision(
                scan_page=result_data["scan_page"],
                heading_text=title,
                include=True,
                title=title,
                level=level,
                entry_number=missing.identifier,
                reasoning=f"Found heading '{missing.identifier}' in search range. {result_data.get('reasoning', '')}"
            )
            found_count += 1

            stage_storage.save_file(
                f"evaluation/missing_{missing.identifier.replace(' ', '_')}.json",
                decision.model_dump()
            )
        else:
            reason = result_data.get("reasoning", "Not found in search range") if result_data else "Agent did not complete"
            logger.info(f"Missing '{missing.identifier}' not found: {reason}")

            decision = HeadingDecision(
                scan_page=None,
                heading_text=title,
                include=False,
                title=title,
                level=level,
                entry_number=missing.identifier,
                reasoning=f"Searched range {missing.predicted_page_range} but not found. {reason}"
            )
            stage_storage.save_file(
                f"evaluation/missing_{missing.identifier.replace(' ', '_')}.json",
                decision.model_dump()
            )

    logger.info(f"Missing search complete: {found_count}/{len(candidates_to_search)} found")

    return found_count


def _build_toc_entries_by_page(stage_storage) -> Dict[int, str]:
    linked_toc_data = stage_storage.load_file("linked_toc.json")
    if not linked_toc_data:
        return {}

    entries_by_page = {}
    for entry in linked_toc_data.get("entries", []):
        if entry and entry.get("scan_page"):
            entries_by_page[entry["scan_page"]] = entry.get("title", "")
    return entries_by_page


def evaluate_candidates(
    tracker: PhaseStatusTracker,
    model: str = None,
    **kwargs
) -> Dict[str, Any]:
    storage = tracker.storage
    logger = tracker.logger
    stage_storage = tracker.stage_storage

    model = model or Config.vision_model_primary

    pattern_data = stage_storage.load_file("pattern/pattern_analysis.json")
    if not pattern_data:
        logger.info("No pattern analysis found - skipping evaluation")
        return {}

    pattern = PatternAnalysis(**pattern_data)

    toc_entries_by_page = _build_toc_entries_by_page(stage_storage)

    excluded_ranges = pattern.excluded_page_ranges
    candidates_to_eval = []
    excluded_count = 0

    if pattern.candidate_headings:
        for candidate in pattern.candidate_headings:
            if is_in_excluded_range(candidate.scan_page, excluded_ranges):
                excluded_count += 1
            else:
                candidates_to_eval.append(candidate.model_dump())

        if excluded_count > 0:
            logger.info(f"Excluded {excluded_count} candidates in excluded page ranges")

    has_candidates = len(candidates_to_eval) > 0
    missing_entries = _extract_missing_entries(pattern.discovered_patterns, pattern.body_range)
    has_missing = len(missing_entries) > 0

    if not has_candidates and not has_missing:
        logger.info("No candidate headings and no missing predictions - nothing to evaluate")
        return {}

    result = {}

    if candidates_to_eval:
        logger.info(f"Evaluating {len(candidates_to_eval)} candidate headings with vision...")

        patterns = pattern.discovered_patterns
        toc_summary = f"Body range: pages {pattern.body_range[0]}-{pattern.body_range[1]}"

        # Build list of (index, candidate) for all non-excluded candidates
        all_candidates = pattern.candidate_headings
        candidates_by_index = {}
        for i, c in enumerate(all_candidates):
            if not is_in_excluded_range(c.scan_page, excluded_ranges):
                candidates_by_index[i] = c.model_dump()

        result = LLMBatchProcessor(LLMBatchConfig(
            tracker=tracker,
            model=model,
            batch_name="evaluation",
            request_builder=lambda item, storage, **kw: prepare_evaluation_request(
                item=item,
                candidate=candidates_by_index[item],
                storage=storage,
                patterns=patterns,
                toc_summary=toc_summary,
                toc_entries_by_page=toc_entries_by_page
            ),
            result_handler=create_evaluation_handler(
                stage_storage=stage_storage,
                logger=logger,
                candidates_by_index=candidates_by_index,
                metrics_prefix=tracker.metrics_prefix,
            ),
            max_workers=10,
            max_retries=3,
        )).process()
    else:
        logger.info("No candidate headings to evaluate")

    missing_found = search_missing_candidates(tracker, pattern, model)

    eval_dir = stage_storage.output_dir / "evaluation"
    if eval_dir.exists():
        included = 0
        excluded = 0
        missing_included = 0

        for f in eval_dir.glob("heading_*.json"):
            data = stage_storage.load_file(f"evaluation/{f.name}")
            if data and data.get("include"):
                included += 1
            else:
                excluded += 1

        for f in eval_dir.glob("missing_*.json"):
            data = stage_storage.load_file(f"evaluation/{f.name}")
            if data and data.get("include"):
                missing_included += 1

        logger.info(f"Evaluation complete: {included} candidates included, {excluded} excluded")
        if missing_included > 0 or missing_entries:
            logger.info(f"Missing heading search: {missing_included}/{len(missing_entries)} candidates found")

    return result
