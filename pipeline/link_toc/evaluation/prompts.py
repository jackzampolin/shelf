EVALUATION_SYSTEM_PROMPT = """You evaluate whether a candidate heading belongs in the book's enriched Table of Contents.

All page numbers are SCAN pages (physical position in PDF), not printed page numbers.

You will see a page image and context about the candidate heading.

## Your task
Look at the page image and determine if this heading represents a NEW structural division that should be ADDED to the ToC.

## Critical: Same-page ToC entries
If there's already a ToC entry on this page, the candidate is almost always a false positive:
- "CHAPTER FIVE" above the actual chapter title "First Commands" → exclude (decorative)
- "Leahy" on a page with "Leahy: The Judge—Annapolis" → exclude (partial/shortened)
- Part numbers, date ranges, or subtitles on chapter start pages → exclude

## Other false positives
- Running headers (chapter titles repeated at top of pages)
- Section dividers in back matter
- OCR artifacts, page numbers, figure captions

## When uncertain
Lean toward excluding - it's better to miss a marginal heading than include duplicates.

## Output format
{
  "include": true/false,
  "title": "cleaned title if include",
  "level": 1-3,
  "entry_number": "Chapter 5" or null,
  "reasoning": "explain your decision"
}"""


def build_evaluation_prompt(candidate, observations, toc_context, nearby_toc_entries=""):
    obs_text = "\n".join(f"- {obs}" for obs in observations) if observations else "No specific observations"

    nearby_section = ""
    if nearby_toc_entries:
        nearby_section = f"\n\n## Nearby ToC Entries\n{nearby_toc_entries}"

    toc_on_page = ""
    if candidate.toc_entry_on_page:
        toc_on_page = f'\n- ⚠️ EXISTING ToC entry on this page: "{candidate.toc_entry_on_page}"'

    return f"""## Pattern Observations
{obs_text}

## ToC Context
{toc_context}{nearby_section}

## Candidate
- Page: {candidate.scan_page}
- Text: "{candidate.heading_text}"{toc_on_page}
- Preceding ToC page: {candidate.preceding_toc_page}
- Following ToC page: {candidate.following_toc_page}"""
