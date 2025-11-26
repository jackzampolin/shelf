import json
from typing import Dict, Any, Optional, Tuple, List

from infra.llm.batch import LLMBatchProcessor, LLMBatchConfig
from infra.llm.agent import AgentConfig, AgentBatchConfig, AgentBatchClient
from infra.pipeline.status import PhaseStatusTracker
from infra.config import Config

from ..schemas import PatternAnalysis, HeadingDecision, MissingCandidateHeading
from .request_builder import prepare_evaluation_request
from .result_handler import create_evaluation_handler
from .agent import MissingHeadingSearchTools, SEARCHER_SYSTEM_PROMPT, build_searcher_user_prompt


def is_in_excluded_range(page_num: int, excluded_ranges: list) -> bool:
    """Check if a page is in any excluded range."""
    for ex_range in excluded_ranges:
        if ex_range.start_page <= page_num <= ex_range.end_page:
            return True
    return False


def _get_excluded_pages_for_candidate(
    missing: MissingCandidateHeading,
    excluded_ranges: list,
    stage_storage
) -> List[int]:
    """Get list of pages to exclude for a missing candidate search."""
    excluded = []
    start_page, end_page = missing.predicted_page_range

    for page_num in range(start_page, end_page + 1):
        # Exclude if in excluded range
        if is_in_excluded_range(page_num, excluded_ranges):
            excluded.append(page_num)
        # Exclude if already evaluated in main batch
        existing_eval = stage_storage.output_dir / "evaluation" / f"heading_{page_num:04d}.json"
        if existing_eval.exists():
            excluded.append(page_num)

    return excluded


def search_missing_candidates(
    tracker: PhaseStatusTracker,
    pattern: PatternAnalysis,
    model: str,
) -> int:
    """Search for predicted missing headings using parallel agents.

    Each missing candidate gets its own agent that searches pages in the predicted range.
    All agents run in parallel.

    Returns the number of missing headings found.
    """
    storage = tracker.storage
    logger = tracker.logger
    stage_storage = tracker.stage_storage

    missing_candidates = pattern.missing_candidate_headings
    if not missing_candidates:
        return 0

    # Filter out already-processed missing candidates
    candidates_to_search = []
    for missing in missing_candidates:
        found_file = stage_storage.output_dir / "evaluation" / f"missing_{missing.identifier.replace(' ', '_')}.json"
        if not found_file.exists():
            candidates_to_search.append(missing)

    if not candidates_to_search:
        logger.info("Missing candidate search: all already processed")
        return 0

    logger.info(f"Searching for {len(candidates_to_search)} predicted missing headings...")

    # Build agent configs for each missing candidate
    configs = []
    tools_list = []

    for missing in candidates_to_search:
        agent_id = f"search-{missing.identifier.replace(' ', '-')}"

        # Get excluded pages for this candidate's range
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
            max_iterations=15  # Enough to check several pages
        ))

    # Run all agents in parallel
    batch_config = AgentBatchConfig(
        tracker=tracker,
        agent_configs=configs,
        batch_name="link-toc-missing-search",
        max_workers=len(configs)  # All in parallel
    )

    batch = AgentBatchClient(batch_config)
    batch_result = batch.run()

    # Process results and save decisions (results are in same order as configs)
    found_count = 0

    for agent_result, tools, missing in zip(batch_result.results, tools_list, candidates_to_search):
        result_data = tools._pending_result

        if result_data and result_data.get("found") and result_data.get("scan_page"):
            decision = HeadingDecision(
                scan_page=result_data["scan_page"],
                heading_text=result_data.get("heading_text", missing.identifier),
                include=True,
                title=result_data.get("heading_text", missing.identifier),
                level=1,  # Missing headings are typically top-level chapters
                entry_number=missing.identifier,
                parent_toc_entry_index=None,
                reasoning=f"Found predicted missing heading '{missing.identifier}'. {result_data.get('reasoning', '')}"
            )
            found_count += 1

            stage_storage.save_file(
                f"evaluation/missing_{missing.identifier.replace(' ', '_')}.json",
                decision.model_dump()
            )
        else:
            # Not found - just log it, don't save a decision file
            # (We'll search again next time if needed)
            reason = result_data.get("reasoning", "Not found in predicted range") if result_data else "Agent did not complete"
            logger.info(f"Missing '{missing.identifier}' not found: {reason}")

    logger.info(f"Missing search complete: {found_count}/{len(candidates_to_search)} found")

    return found_count


def evaluate_candidates(
    tracker: PhaseStatusTracker,
    model: str = None,
    **kwargs
) -> Dict[str, Any]:
    """Evaluate candidate headings using vision LLM."""

    storage = tracker.storage
    logger = tracker.logger
    stage_storage = tracker.stage_storage

    model = model or Config.vision_model_primary

    # Load pattern analysis
    pattern_data = stage_storage.load_file("pattern/pattern_analysis.json")
    if not pattern_data:
        logger.info("No pattern analysis found - skipping evaluation")
        return {}

    pattern = PatternAnalysis(**pattern_data)

    # Filter out excluded page ranges
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

    # Check if there's anything to do
    has_candidates = len(candidates_to_eval) > 0
    has_missing = len(pattern.missing_candidate_headings) > 0

    if not has_candidates and not has_missing:
        logger.info("No candidate headings and no missing predictions - nothing to evaluate")
        return {}

    result = {}

    # Evaluate candidate headings (if any)
    if candidates_to_eval:
        logger.info(f"Evaluating {len(candidates_to_eval)} candidate headings with vision...")

        # Build context for requests
        observations = pattern.observations
        toc_summary = f"ToC has {pattern.toc_structure.get('count', 0)} entries, body range: {pattern.body_range}"

        # Create lookup for result handler
        candidates_by_page = {c["scan_page"]: c for c in candidates_to_eval}

        # Override tracker's get_remaining_items to return our filtered candidates
        original_get_remaining = tracker.get_remaining_items

        def get_filtered_candidates():
            # Check which are already done
            remaining = []
            for candidate in candidates_to_eval:
                decision_file = stage_storage.output_dir / "evaluation" / f"heading_{candidate['scan_page']:04d}.json"
                if not decision_file.exists():
                    remaining.append(candidate)
            return remaining

        tracker.get_remaining_items = get_filtered_candidates

        try:
            result = LLMBatchProcessor(LLMBatchConfig(
                tracker=tracker,
                model=model,
                batch_name="Heading evaluation",
                request_builder=lambda item, storage, **kw: prepare_evaluation_request(
                    item=item,
                    storage=storage,
                    observations=observations,
                    toc_summary=toc_summary
                ),
                result_handler=create_evaluation_handler(
                    stage_storage=stage_storage,
                    logger=logger,
                    candidates_by_page=candidates_by_page
                ),
                max_workers=10,
                max_retries=3,
            )).process()
        finally:
            tracker.get_remaining_items = original_get_remaining
    else:
        logger.info("No candidate headings to evaluate")

    # Search for predicted missing headings
    missing_found = search_missing_candidates(tracker, pattern, model)

    # Count results
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
        if missing_included > 0 or pattern.missing_candidate_headings:
            logger.info(f"Missing heading search: {missing_included}/{len(pattern.missing_candidate_headings)} predicted headings found")

    return result
