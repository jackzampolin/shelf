SEARCHER_SYSTEM_PROMPT = """You search for a SPECIFIC missing chapter heading in a page range.

All page numbers are SCAN pages (physical position in PDF), not printed page numbers.

## CRITICAL: Be CONSERVATIVE

You are searching for ONE SPECIFIC missing entry (e.g., "Chapter 14" in a sequence of 1-38).
This is NOT a general search for any heading or structural break.

**Default answer: found=false**

Report found=true ONLY if you find the EXACT expected heading or a clear equivalent.
Do NOT report found for subheadings, section titles, or vague content shifts.

## Why you're searching
The pattern analysis detected a gap in a sequential pattern (e.g., chapters 1, 2, 3, 5, 6 missing "4").
The heading MAY exist but OCR might have missed it.

## Strategy
1. get_range_ocr → Look for text matching the expected identifier (e.g., "14", "Chapter 14", "CHAPTER XIV")
2. view_page_image → REQUIRED before reporting found. Visually confirm the heading exists.

## What counts as "found"
- The EXACT expected identifier (e.g., "14", "CHAPTER 14", "Chapter Fourteen")
- A clear heading at the TOP of a page that matches the pattern
- Visual confirmation of large/bold text with the expected number/name

## What does NOT count as "found"
- Subheadings or section titles within chapters
- Content breaks without clear heading text
- Any prominent text that doesn't match the expected identifier
- "It looks like a chapter start" without the actual identifier

## When to report not found
If you cannot find the EXACT expected heading after checking OCR and page images:
- Report found=false
- It's okay to miss one entry - the validation phase will investigate gaps later
- Do NOT invent structure that doesn't clearly exist"""


def build_searcher_user_prompt(missing_candidate, excluded_pages=None):
    start_page, end_page = missing_candidate.predicted_page_range
    excluded_note = f"\n\nSkip pages: {excluded_pages}" if excluded_pages else ""

    # Build pattern context
    pattern_context = ""
    if missing_candidate.pattern_description:
        pattern_context = f"\n\n## Pattern Context\n- Pattern: {missing_candidate.pattern_description}"
        if missing_candidate.pattern_found and missing_candidate.pattern_expected:
            pattern_context += f"\n- Found: {missing_candidate.pattern_found}/{missing_candidate.pattern_expected} ({missing_candidate.pattern_found/missing_candidate.pattern_expected*100:.0f}% confidence)"
        if missing_candidate.avg_pages_per_entry:
            pattern_context += f"\n- Avg pages per {missing_candidate.level_name or 'entry'}: ~{missing_candidate.avg_pages_per_entry}"

    return f"""## Missing Heading Search

Looking for: "{missing_candidate.identifier}" ({missing_candidate.level_name or 'entry'})
Search range: pages {start_page} to {end_page}{pattern_context}

This entry is expected based on the sequential pattern but wasn't found in candidate headings.{excluded_note}"""
