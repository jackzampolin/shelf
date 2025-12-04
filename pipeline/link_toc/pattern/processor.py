import bisect

from infra.llm.single import LLMSingleCall, LLMSingleCallConfig
from infra.config import Config
from ..schemas import LinkedTableOfContents, PatternAnalysis, CandidateHeading, MissingCandidateHeading, ExcludedPageRange
from .prompts import PATTERN_SYSTEM_PROMPT, build_pattern_prompt


def analyze_toc_pattern(tracker, **kwargs):
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

    all_headings = _load_all_headings(storage, logger)
    if not all_headings:
        return

    body_range = (min(toc_pages), max(toc_pages))
    toc_titles_by_page = {e.scan_page: e.title for e in toc_entries if e.scan_page}

    candidate_headings = _build_candidates(all_headings, body_range, toc_pages, toc_titles_by_page)
    logger.info(f"ToC: {len(toc_pages)} pages, Candidates: {len(candidate_headings)} headings in body")

    observations, missing, excluded, requires_eval, reasoning = _analyze_with_llm(
        tracker, model, logger, toc_entries, candidate_headings, body_range
    )

    pattern_analysis = PatternAnalysis(
        body_range=body_range,
        candidate_headings=candidate_headings,
        observations=observations,
        missing_candidate_headings=missing,
        excluded_page_ranges=excluded,
        requires_evaluation=requires_eval,
        reasoning=reasoning
    )

    storage.stage("link-toc").save_file(
        "pattern/pattern_analysis.json",
        pattern_analysis.model_dump(),
        schema=PatternAnalysis
    )

    logger.info(f"Pattern analysis: {len(observations)} observations, {len(missing)} missing predictions")


def _load_all_headings(storage, logger):
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


def _build_candidates(all_headings, body_range, toc_pages, toc_titles_by_page):
    candidates = []
    for h in all_headings:
        page = h["scan_page"]
        if not (body_range[0] <= page <= body_range[1]):
            continue

        toc_entry_on_page = toc_titles_by_page.get(page)
        if toc_entry_on_page and _text_matches(h["text"], toc_entry_on_page):
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
            toc_entry_on_page=toc_entry_on_page
        ))

    return candidates


def _text_matches(heading_text, toc_title):
    return heading_text.lower().strip() == toc_title.lower().strip()


def _analyze_with_llm(tracker, model, logger, toc_entries, candidate_headings, body_range):
    if not candidate_headings:
        return [], [], [], True, "No candidates to analyze"

    logger.info(f"Calling LLM to analyze {len(candidate_headings)} candidates...")

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
                        "observations": {
                            "type": "array",
                            "items": {"type": "string"}
                        },
                        "missing_candidate_headings": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "identifier": {"type": "string"},
                                    "predicted_page_range": {
                                        "type": "array",
                                        "items": {"type": "integer"},
                                        "minItems": 2,
                                        "maxItems": 2
                                    },
                                    "confidence": {"type": "number"},
                                    "reasoning": {"type": "string"}
                                },
                                "required": ["identifier", "predicted_page_range", "confidence", "reasoning"],
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
                        "requires_evaluation": {"type": "boolean"},
                        "reasoning": {"type": "string"}
                    },
                    "required": ["observations", "missing_candidate_headings", "excluded_page_ranges", "requires_evaluation", "reasoning"],
                    "additionalProperties": False
                }
            }
        },
        max_tokens=3000,
    )

    if not result.success or not result.parsed_json:
        logger.warning(f"Pattern analysis failed: {result.error_message}")
        return [], [], [], True, f"LLM call failed: {result.error_message}"

    data = result.parsed_json
    observations = data.get("observations", [])
    reasoning = data.get("reasoning", "")
    requires_eval = data.get("requires_evaluation", True)

    missing = []
    for mc in data.get("missing_candidate_headings", []):
        try:
            missing.append(MissingCandidateHeading(
                identifier=mc["identifier"],
                predicted_page_range=tuple(mc["predicted_page_range"]),
                confidence=mc.get("confidence", 0.5),
                reasoning=mc.get("reasoning", "")
            ))
        except (KeyError, TypeError):
            pass

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

    logger.info(f"LLM: {len(observations)} observations, {len(missing)} missing, {len(excluded)} excluded")
    if not requires_eval:
        logger.info("LLM determined evaluation not needed - all candidates are noise")

    return observations, missing, excluded, requires_eval, reasoning
