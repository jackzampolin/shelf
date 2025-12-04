SEARCHER_SYSTEM_PROMPT = """You search for a chapter heading that may exist in a specific page range.

All page numbers are SCAN pages (physical position in PDF), not printed page numbers.

## How tools work together
1. get_heading_pages → See what headings were detected in the search range
2. grep_text → Find pages with text matches
3. get_page_ocr → Read page text to verify
4. view_page_image → Visual confirmation when OCR is unclear
5. write_result → Report findings

## Strategy
Search the page range systematically. Report what you actually find - if the heading doesn't exist, report not found.

## When to stop
Report not found if you've checked promising pages and haven't found a clear match. Don't force a match."""


def build_searcher_user_prompt(missing_candidate, excluded_pages=None):
    start_page, end_page = missing_candidate.predicted_page_range
    excluded_note = f"\n\nSkip pages: {excluded_pages}" if excluded_pages else ""

    return f"""## Missing Heading Search

Looking for: "{missing_candidate.identifier}"
Search range: pages {start_page} to {end_page}

Why expected: {missing_candidate.reasoning}{excluded_note}"""
