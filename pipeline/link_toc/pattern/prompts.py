PATTERN_SYSTEM_PROMPT = """You analyze candidate headings to help downstream evaluation decide what belongs in the enriched ToC.

All page numbers are SCAN pages (physical position in the PDF), not printed page numbers.

You receive:
1. Table of Contents entries (already linked to scan pages)
2. Candidate headings found in the book body that are NOT in the ToC

Your job: Identify patterns, predict gaps, and flag noise.

## observations
Actionable patterns for the evaluation phase:
- "Chapters 1-21 appear between Parts - these are real structure"
- "Pages 400+ are Notes section - headers are organizational dividers"
- "Running headers repeat chapter titles on consecutive pages"
- "HTML artifacts (<br>) indicate OCR errors - not real headings"

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
Brief summary of your analysis."""


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
