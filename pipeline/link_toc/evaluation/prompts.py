EVALUATION_SYSTEM_PROMPT = """You evaluate whether a candidate heading belongs in the book's enriched Table of Contents.

All page numbers are SCAN pages (physical position in PDF), not printed page numbers.

You will see a page image and context about the candidate heading.

## Your task
Look at the page image and determine if this heading represents a structural division in the book (chapter, part, section) that should appear in the ToC.

## Common false positives to check for
- Running headers: chapter titles often repeat at the top of every page within that chapter
- Section dividers in back matter that organize references, not body content
- OCR artifacts, page numbers, or figure captions misdetected as headings

## When uncertain
If you cannot clearly determine from the image, lean toward excluding - it's better to miss a marginal heading than include noise."""


def build_evaluation_prompt(candidate, observations, toc_context, nearby_toc_entries=""):
    obs_text = "\n".join(f"- {obs}" for obs in observations) if observations else "No specific observations"

    nearby_section = ""
    if nearby_toc_entries:
        nearby_section = f"\n\n## Nearby ToC Entries\n{nearby_toc_entries}"

    return f"""## Pattern Observations
{obs_text}

## ToC Context
{toc_context}{nearby_section}

## Candidate
- Page: {candidate.scan_page}
- Text: "{candidate.heading_text}"
- Preceding ToC page: {candidate.preceding_toc_page}
- Following ToC page: {candidate.following_toc_page}"""
