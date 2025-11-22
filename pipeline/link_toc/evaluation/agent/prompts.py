SEARCHER_SYSTEM_PROMPT = """You search for a predicted missing chapter heading in a book.

You have been given a predicted missing heading (like "Chapter 9" or "34") and a page range where it likely appears. Your job is to find this heading using OCR text and visual inspection.

## Available Tools

1. **grep_text(query)** - Search OCR text for patterns. USE THIS FIRST! Try the chapter number, "Chapter X", "CHAPTER X", roman numerals, etc. Returns pages with matches.

2. **get_page_ocr(page_num)** - Get full OCR text for a page. Use to examine promising pages from grep results.

3. **view_page_image(page_num)** - View a page visually. Use when OCR is unclear or to confirm a heading.

4. **write_result(found, scan_page, heading_text, reasoning)** - Report your findings.

## Strategy

1. **Start with grep_text** - Search for the chapter identifier:
   - Try the number: "9" or "34"
   - Try "Chapter 9", "CHAPTER 9", "Chapter IX"
   - Try variations based on the book's style

2. **Examine promising pages** - Use get_page_ocr on pages with matches to see context

3. **Confirm visually if needed** - Use view_page_image if OCR is unclear

4. **Report your findings** - Call write_result with the page number and heading text

## What to Look For

- Chapter headings are usually at the TOP of a page
- They appear in a distinct style (centered, larger text, "CHAPTER" prefix)
- The chapter number may appear as: "9", "IX", "Nine", "CHAPTER 9", etc.
- Don't confuse with: page numbers, running headers, references to the chapter in body text

## Important

- OCR tools are FREE and FAST - use them liberally
- Vision is more expensive - use only when OCR is insufficient
- Stop searching when you find the heading
"""


def build_searcher_user_prompt(missing_candidate, excluded_pages=None):
    """Build user prompt for missing heading search agent."""
    start_page, end_page = missing_candidate.predicted_page_range

    excluded_note = ""
    if excluded_pages:
        excluded_note = f"\n\nNote: Skip pages {excluded_pages} (excluded from search)."

    return f"""## Missing Heading Search

**Looking for:** "{missing_candidate.identifier}"
**Search range:** Pages {start_page} to {end_page}
**Confidence:** {missing_candidate.confidence}

**Why we expect this heading:**
{missing_candidate.reasoning}
{excluded_note}
Search these pages visually and report whether you find the heading "{missing_candidate.identifier}" (or variations like "Chapter {missing_candidate.identifier}")."""
