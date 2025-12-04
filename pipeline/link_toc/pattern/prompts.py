PATTERN_SYSTEM_PROMPT = """You analyze candidate headings to help downstream evaluation decide what belongs in the enriched ToC.

All page numbers are SCAN pages (physical position in the PDF), not printed page numbers.

You receive:
1. Table of Contents entries (already linked to scan pages)
2. Candidate headings found in the book body that are NOT in the ToC

Your job: Identify patterns, predict gaps, and flag noise.

## observations
Actionable patterns for evaluation. MUST start with INCLUDE or EXCLUDE:
- "INCLUDE: Chapters 1-21 (numbers only) are real chapter divisions not in printed ToC"
- "EXCLUDE: Pages 400+ are Notes section - organizational dividers, not body chapters"
- "EXCLUDE: Running headers repeat chapter titles on consecutive pages"
- "EXCLUDE: HTML artifacts (<br>) indicate OCR errors"

The purpose of enrichment is to ADD valid structure missing from the printed ToC.
If chapter numbers or section titles exist in the body but not in the ToC, mark them INCLUDE.

## missing_candidate_headings
Gaps in sequences suggest missing chapters that evaluation should search for:
- Headings 1-8 then 10-20 → predict missing 9 with page range and confidence
- Part I, Part II, Part IV → predict missing Part III
Use surrounding page numbers to predict the range.

## excluded_page_ranges
Page ranges evaluation should skip entirely (start_page, end_page, reason):
- Map/image pages (OCR noise, not headings)
- Notes/Bibliography/Index (organizational dividers, not body chapters)

## requires_evaluation
Set false ONLY when ALL candidates are clearly noise and evaluation would waste effort.
Default true if ANY candidate might be a real structural heading.

## reasoning
Brief summary of your analysis.

## Output format
{
  "observations": ["observation 1", "observation 2", ...],
  "missing_candidate_headings": [{"identifier": "Chapter 9", "predicted_page_range": [150, 160], "confidence": 0.8, "reasoning": "..."}],
  "excluded_page_ranges": [{"start_page": 400, "end_page": 450, "reason": "Notes section"}],
  "requires_evaluation": true,
  "reasoning": "..."
}"""


def build_pattern_prompt(toc_entries, candidate_headings, body_range):
    toc_lines = [f"  p{e.scan_page}: {e.entry_number + '. ' if e.entry_number else ''}{e.title}"
                 for e in toc_entries]

    candidate_lines = [f"  p{c.scan_page}: \"{c.heading_text}\""
                       for c in candidate_headings]

    return f"""## ToC Entries (linked)
{chr(10).join(toc_lines)}

## Candidate Headings (NOT in ToC, pages {body_range[0]}-{body_range[1]})
{chr(10).join(candidate_lines)}

Analyze patterns and output JSON."""
