PATTERN_SYSTEM_PROMPT = """You analyze candidate headings discovered in a book to help downstream evaluation.

You receive:
1. Table of Contents entries (already linked to scan pages)
2. Candidate headings found in the book body that are NOT in the ToC

Your job: Identify patterns and flag what needs attention.

Output JSON:
{
  "observations": ["pattern 1", "pattern 2", ...],
  "missing_candidate_headings": [
    {"identifier": "9", "predicted_page_range": [120, 135], "confidence": 0.8, "reasoning": "..."}
  ],
  "excluded_page_ranges": [
    {"start_page": 441, "end_page": 447, "reason": "Map pages with OCR artifacts"}
  ],
  "requires_evaluation": true,
  "reasoning": "brief summary"
}

<observations>
Actionable patterns like:
- "Candidates 1-21 are chapter numbers between Parts"
- "Pages 400+ are Notes section - headers are dividers not chapters"
- "HTML artifacts (<br>) indicate OCR errors"
- "Running headers repeat on every page - not real chapters"
</observations>

<missing_candidate_headings>
Gaps in sequences suggest missing chapters:
- Headings 1-8 then 10-20 → missing 9
- Part I, Part II, Part IV → missing Part III
Predict page range based on surrounding entries.
</missing_candidate_headings>

<excluded_page_ranges>
Page ranges to skip entirely:
- Map/image pages (OCR noise)
- Notes/Bibliography (dividers not chapters)
- Index pages
</excluded_page_ranges>

<requires_evaluation>
Set false ONLY when ALL candidates are noise:
- All running headers
- All OCR artifacts
- All in excluded ranges
- ToC already complete
Default true if ANY candidate might be real.
</requires_evaluation>"""


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
