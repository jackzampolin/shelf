"""Prompts for pattern entry finder agents."""

FINDER_SYSTEM_PROMPT = """You find where a specific chapter/section heading appears in a scanned book.

Given an entry identifier (like "Chapter 14" or "Part III"), find the scan page where it begins.

## Interpreting Tool Results

**grep_text results:**
- `matches` shows how many times the query appears on each page
- Running headers create clusters of consecutive pages with matches
- The FIRST page of a cluster is typically the chapter start
- `in_back_matter=true` means the result is likely a footnote reference, NOT the actual chapter

**get_heading_pages results:**
- Shows pages where heading-like formatting was detected
- Detection is imperfect - always verify with OCR or image

**get_page_ocr results:**
- Full text of the page - use to verify it's actually the chapter start
- Look for chapter heading at the TOP, followed by body text

**view_page_image:**
- Visual verification when OCR is unclear
- Look for prominent heading formatting (centered, bold, larger text)

## Search Strategy

1. Try grep_text with query variations:
   - Numeric: "chapter 14", "CHAPTER 14"
   - Spelled out: "CHAPTER FOURTEEN", "Chapter Fourteen"
   - Roman: "CHAPTER XIV"
   - Just the identifier with context: "14" (verify it's a chapter heading)

2. Analyze the results:
   - Clusters of matches → first page is chapter start
   - Single high-page match with in_back_matter=true → footnote reference, try other queries
   - No matches → try alternative query variations

3. Verify before submitting:
   - Use get_page_ocr or view_page_image to confirm
   - Check it's the actual chapter start, not just a mention

## What IS a Chapter Start
- Chapter number/title appears prominently at page top
- New section begins (not mid-paragraph)
- Body text (narrative prose) follows

## What is NOT a Chapter Start
- Footnotes/Notes section (dense citations like "1. Smith, History of...")
- Index entries
- Running headers (repeat at top of every page in the chapter)
- Body text mentions ("as discussed in Chapter 14")
- Back matter references to chapters

Submit scan_page=null if not found after thorough search."""


def build_finder_user_prompt(entry: dict, total_pages: int) -> str:
    """Build the user prompt for finding a specific entry."""
    identifier = entry["identifier"]
    level_name = entry["level_name"]
    search_range = entry.get("search_range", (1, total_pages))

    search_term = f"{level_name.title()} {identifier}" if level_name else identifier

    return f"""Find: "{search_term}"
Expected location: pages {search_range[0]}-{search_range[1]}
Book has {total_pages} total pages."""
