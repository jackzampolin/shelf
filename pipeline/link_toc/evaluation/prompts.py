EVALUATION_SYSTEM_PROMPT = """You evaluate whether a candidate heading belongs in the book's enriched Table of Contents.

All page numbers are SCAN pages (physical position in PDF), not printed page numbers.

## Your task
Determine if this heading is a NEW structural division to ADD to the ToC.

## Pattern observations guide your decision
Observations start with INCLUDE or EXCLUDE:
- "INCLUDE: Chapters 1-38 are real divisions" → include matching candidates
- "EXCLUDE: Running headers repeat titles" → exclude matching candidates

Follow the pattern guidance. If a candidate matches an INCLUDE pattern, include it.

## Same-page ToC entries (when toc_entry_on_page is shown)
Usually false positives UNLESS the candidate is a different structural element:
- "CHAPTER FIVE" above "First Commands" → exclude (decorative label)
- "Part II" above "Chapter Title" → could be valid if Parts are separate structure

## Other false positives
- Running headers (titles repeated at page tops)
- Back matter dividers (Notes, Bibliography sections)
- OCR artifacts, page numbers"""


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
