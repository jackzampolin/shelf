from infra.llm.single import LLMSingleCall, LLMSingleCallConfig
from infra.config import Config
from ..schemas import LinkedTableOfContents, PatternAnalysis, CandidateHeading, MissingCandidateHeading, ExcludedPageRange


PATTERN_SYSTEM_PROMPT = """You analyze book structure to identify patterns in discovered headings.

You will receive:
1. The book's Table of Contents (what's already indexed)
2. Candidate headings discovered in the book that are NOT in the ToC

Your job:
1. Identify patterns that help evaluation agents decide which candidates are real structural headings vs noise
2. Detect any MISSING chapters (gaps in sequences) and predict where they likely are

Output a JSON object with:
{
  "observations": [
    "observation 1 about patterns you see",
    "observation 2...",
    ...
  ],
  "missing_candidate_headings": [
    {
      "identifier": "9",
      "predicted_page_range": [120, 135],
      "confidence": 0.8,
      "reasoning": "Headings 8 and 10 found at pages 115 and 140, heading 9 should be between them"
    },
    ...
  ],
  "excluded_page_ranges": [
    {
      "start_page": 441,
      "end_page": 447,
      "reason": "Map pages with OCR artifacts (scale markers, grid labels)"
    },
    {
      "start_page": 417,
      "end_page": 454,
      "reason": "Notes section - chapter headers are organizational dividers, not body headings"
    },
    ...
  ],
  "reasoning": "brief explanation of your analysis"
}

Focus on actionable observations like:
- "Candidates 1-21 appear to be chapter numbers (1, 2, 3...) between Parts"
- "Headings after page X are in the Notes section - likely references, not chapters"
- "Some headings contain HTML artifacts (<br>) indicating OCR errors"
- "Pattern: Part I contains chapters 1-4, Part II contains chapters 5-8..."

For missing_candidate_headings, look for:
- Gaps in numeric sequences (e.g., headings 1-8 then 10-20, missing 9)
- Missing parts in a series (e.g., Part I, Part II, Part IV - missing Part III)
- Expected structural headings not found in candidates

STRUCTURAL EVIDENCE FROM BACK MATTER:
A book's structure may be reflected in multiple places. Notes and Bibliography sections
are often organized by chapter or part - when you see sequential structural headers in
back matter (Chapter 1, Chapter 2... or Part I, Part II...), this can reveal the book's
actual structure even when those headings weren't detected in the body.

Look for:
- Sequential headers that serve as organizational dividers (not inline citations)
- Consistent spacing suggesting section boundaries
- Headers that match the book's structural pattern

When back matter reveals a more complete structure than body candidates, use it to
identify which chapters are genuinely missing from detection. These back matter
references are strong evidence - predict where the missing chapters should appear
in the body based on page ranges and spacing patterns.

EXCLUDING PAGE RANGES:
Use excluded_page_ranges to flag entire page ranges that should NOT be evaluated as candidates:
- Map pages (scale markers, grid labels, geographic names from OCR)
- Image gallery pages (figure captions, plate numbers)
- Notes/Bibliography sections where chapter headers are organizational dividers
- Index pages with dense OCR artifacts
- Any page range with predominantly noise rather than structural headings

This prevents the evaluation phase from wasting effort on obvious non-candidates.
"""


def build_pattern_prompt(toc_entries, candidate_headings, body_range):
    toc_summary = []
    for e in toc_entries:
        num = f"{e.entry_number}. " if e.entry_number else ""
        toc_summary.append(f"  Page {e.scan_page}: {num}{e.title}")

    candidates_summary = []
    for c in candidate_headings:
        candidates_summary.append(f"  Page {c.scan_page}: \"{c.heading_text}\"")

    return f"""## Table of Contents (already in book)
{chr(10).join(toc_summary)}

## Candidate Headings (discovered, NOT in ToC)
Body range: pages {body_range[0]} to {body_range[1]}

{chr(10).join(candidates_summary)}

Analyze these candidates and identify patterns that will help evaluation agents."""


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

    if not linked_toc.entries or len(linked_toc.entries) == 0:
        logger.info("No ToC entries - skipping pattern analysis")
        return

    mechanical_dir = storage.stage("label-structure").output_dir / "mechanical"
    if not mechanical_dir.exists():
        logger.warning("label-structure mechanical output not found")
        return

    all_headings = []
    for page_file in sorted(mechanical_dir.glob("page_*.json")):
        page_data = storage.stage("label-structure").load_file(f"mechanical/{page_file.name}")
        if not page_data:
            continue

        page_num = int(page_file.stem.split("_")[1])
        headings = page_data.get("headings", [])

        for heading in headings:
            all_headings.append({
                "scan_page": page_num,
                "text": heading.get("text", ""),
                "level": heading.get("level", 1)
            })

    logger.info(f"Found {len(all_headings)} total headings in label-structure")

    toc_entries = [e for e in linked_toc.entries if e is not None]
    toc_pages = [e.scan_page for e in toc_entries if e.scan_page]

    if not toc_pages:
        logger.warning("No ToC entries with scan_pages - skipping")
        return

    body_range = (min(toc_pages), max(toc_pages))

    toc_page_set = set(toc_pages)
    candidate_headings_raw = [
        h for h in all_headings
        if body_range[0] <= h["scan_page"] <= body_range[1]
        and h["scan_page"] not in toc_page_set
    ]

    logger.info(f"ToC covers {len(toc_pages)} pages, found {len(candidate_headings_raw)} candidate headings in body")

    candidate_headings = []
    for h in candidate_headings_raw:
        preceding = None
        following = None

        for toc_page in toc_pages:
            if toc_page < h["scan_page"]:
                preceding = toc_page
            elif toc_page > h["scan_page"] and following is None:
                following = toc_page
                break

        candidate_headings.append(CandidateHeading(
            scan_page=h["scan_page"],
            heading_text=h["text"],
            heading_level=h["level"],
            preceding_toc_page=preceding,
            following_toc_page=following
        ))

    # Make LLM call to analyze patterns
    observations = []
    missing_candidate_headings = []
    excluded_page_ranges = []
    reasoning = "No candidates to analyze"

    if candidate_headings:
        logger.info(f"Calling LLM to analyze {len(candidate_headings)} candidates...")

        llm = LLMSingleCall(LLMSingleCallConfig(
            tracker=tracker,
            model=model,
            call_name="Pattern analysis",
            metric_key="pattern_llm"
        ))

        prompt = build_pattern_prompt(toc_entries, candidate_headings, body_range)

        result = llm.call(
            messages=[
                {"role": "system", "content": PATTERN_SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            max_tokens=3000,
        )

        if result.success and result.parsed_json:
            observations = result.parsed_json.get("observations", [])
            reasoning = result.parsed_json.get("reasoning", "")
            logger.info(f"LLM identified {len(observations)} observations")

            # Parse missing candidate heading predictions
            raw_missing = result.parsed_json.get("missing_candidate_headings", [])
            for mc in raw_missing:
                try:
                    missing_candidate_headings.append(MissingCandidateHeading(
                        identifier=mc["identifier"],
                        predicted_page_range=tuple(mc["predicted_page_range"]),
                        confidence=mc.get("confidence", 0.5),
                        reasoning=mc.get("reasoning", "")
                    ))
                except (KeyError, TypeError) as e:
                    logger.warning(f"Failed to parse missing candidate heading: {mc}, error: {e}")

            if missing_candidate_headings:
                logger.info(f"LLM predicted {len(missing_candidate_headings)} missing candidate headings")

            # Parse excluded page ranges
            raw_excluded = result.parsed_json.get("excluded_page_ranges", [])
            for ex in raw_excluded:
                try:
                    excluded_page_ranges.append(ExcludedPageRange(
                        start_page=ex["start_page"],
                        end_page=ex["end_page"],
                        reason=ex.get("reason", "")
                    ))
                except (KeyError, TypeError) as e:
                    logger.warning(f"Failed to parse excluded page range: {ex}, error: {e}")

            if excluded_page_ranges:
                logger.info(f"LLM identified {len(excluded_page_ranges)} page ranges to exclude")
        else:
            logger.warning(f"Pattern analysis failed: {result.error_message}")
            reasoning = f"LLM call failed: {result.error_message}"

    # Build structure analysis
    toc_levels = [e.level for e in toc_entries]
    toc_numbers = [e.entry_number for e in toc_entries if e.entry_number]

    numbering_scheme = "none"
    if toc_numbers:
        first_num = toc_numbers[0]
        if first_num.upper() in ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X']:
            numbering_scheme = "roman"
        elif first_num.isdigit():
            numbering_scheme = "arabic"
        else:
            numbering_scheme = "mixed"

    toc_structure = {
        "numbering": numbering_scheme,
        "level": max(set(toc_levels), key=toc_levels.count) if toc_levels else 1,
        "count": len(toc_entries),
        "ascending_pages": all(toc_pages[i] <= toc_pages[i+1] for i in range(len(toc_pages)-1))
    }

    discovered_levels = [h.heading_level for h in candidate_headings]
    discovered_structure = {
        "count": len(candidate_headings),
        "numbering": "unknown",
        "levels": list(set(discovered_levels)) if discovered_levels else []
    }

    pattern_analysis = PatternAnalysis(
        pattern_description=f"ToC has {toc_structure['count']} entries, {len(candidate_headings)} candidates discovered",
        expected_relationship="see_observations",
        body_range=body_range,
        toc_structure=toc_structure,
        discovered_structure=discovered_structure,
        candidate_headings=candidate_headings,
        observations=observations,
        missing_candidate_headings=missing_candidate_headings,
        excluded_page_ranges=excluded_page_ranges,
        confidence=0.8 if observations else 0.3,
        reasoning=reasoning
    )

    storage.stage("link-toc").save_file(
        "pattern/pattern_analysis.json",
        pattern_analysis.model_dump(),
        schema=PatternAnalysis
    )

    logger.info(f"Pattern analysis complete: {len(observations)} observations, {len(missing_candidate_headings)} missing predictions")
    for i, obs in enumerate(observations[:5], 1):
        logger.info(f"  {i}. {obs[:80]}...")
