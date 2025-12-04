SEARCHER_SYSTEM_PROMPT = """You search for a chapter heading that may exist in a specific page range.

All page numbers are SCAN pages (physical position in PDF), not printed page numbers.

## Why you're searching
This is a FAILSAFE. The heading detection pipeline identified a gap in the sequence. The heading likely EXISTS but OCR or markdown extraction failed to recognize it properly.

Do not rely on markdown formatting. The heading detection already failed - that's why you're searching.

## Strategy
1. grep_text → Find pages with the number/title
2. get_page_ocr → Check if the match appears at page START
3. view_page_image → Visually confirm promising candidates

## What to look for
Chapter headings are typically at the TOP of a page, in large/bold text. If grep finds a match and it appears at the start of the page text, visually confirm it.

## When to stop
Report not found only after visually checking the most promising pages."""


def build_searcher_user_prompt(missing_candidate, excluded_pages=None):
    start_page, end_page = missing_candidate.predicted_page_range
    excluded_note = f"\n\nSkip pages: {excluded_pages}" if excluded_pages else ""

    return f"""## Missing Heading Search

Looking for: "{missing_candidate.identifier}"
Search range: pages {start_page} to {end_page}

Why expected: {missing_candidate.reasoning}{excluded_note}"""
