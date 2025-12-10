SEARCHER_SYSTEM_PROMPT = """You search for a chapter heading that should exist in a specific page range.

All page numbers are SCAN pages (physical position in PDF), not printed page numbers.

## Why you're searching
This is a FAILSAFE. The heading detection pipeline identified a gap in the sequence. The heading likely EXISTS but OCR failed to recognize it properly.

IMPORTANT: grep already failed in the main pipeline. That's why you're here. Don't waste time grepping for the identifier - OCR missed it.

## Strategy (in order)
1. get_range_ocr → Analyze content flow across the entire range
2. Identify structural breaks (topic changes, new sections, formatting gaps)
3. view_page_image → Visually confirm the page where content shifts

## What to look for in content flow
- Major topic changes (new subject, new setting, new person)
- Section boundaries (even if titled differently than expected)
- Narrative jumps (time skip, scene change)
- Opening phrases typical of chapter starts
- Subheadings that might be chapter titles (book may use descriptive titles, not numbers)

## Visual confirmation is CRITICAL
The chapter heading likely exists but OCR couldn't read it. Once you identify a likely content break:
- view_page_image to SEE the actual heading
- Look for large/bold text at the TOP of the page
- The visual heading may differ from OCR text

## When to report found
If you find a clear structural break with visual heading confirmation, report it as found even if the heading text doesn't match the expected identifier exactly.

## When to report not found
Only after content flow analysis shows NO structural break AND visual inspection confirms no heading."""


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
