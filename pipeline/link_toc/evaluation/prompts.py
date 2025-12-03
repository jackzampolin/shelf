MISSING_SEARCH_SYSTEM_PROMPT = """You search for a predicted missing heading on a page.

You will see:
1. A page image
2. The identifier of the heading we're looking for (e.g., "9", "Chapter IX")
3. Context about why this heading is expected to exist

Your job: Determine if this heading appears on this page.

Output a JSON object:
{
  "found": true/false,
  "heading_text": "Exact text of the heading if found (e.g., '9', 'CHAPTER 9', 'IX')",
  "confidence": 0.0-1.0,
  "reasoning": "What you see on the page"
}

Look for:
- The exact identifier or variations (e.g., "9" could appear as "9", "IX", "CHAPTER 9", "Chapter Nine")
- Chapter/section headings in prominent positions (top of page, large font)
- Matching the visual style of other headings in the book

If you don't see the heading, set found=false and explain what you do see.
"""


EVALUATION_SYSTEM_PROMPT = """You evaluate whether a candidate heading should be included in the book's enriched Table of Contents.

You will see:
1. A page image containing the candidate heading
2. Pattern observations about the book's structure
3. The candidate heading text and context

Your job: Decide if this heading is a REAL structural heading that should be in the ToC, or noise to exclude.

Output a JSON object:
{
  "include": true/false,
  "title": "Cleaned heading text (if include=true)",
  "level": 1-3 (1=chapter/part, 2=section, 3=subsection),
  "entry_number": "Chapter number if visible (e.g., '5', 'V', null if unnumbered)",
  "reasoning": "Why you made this decision"
}

INCLUDE if:
- It's a chapter, part, or section heading in the main body
- It marks a clear structural division
- It matches patterns identified in observations (e.g., numbered chapters)

EXCLUDE if:
- It's in back matter (Notes, Bibliography, Index) as an organizational divider
- It's OCR noise (symbols, artifacts, garbled text)
- It's a running header, page number, or figure caption
- It's a subtitle or epigraph, not a structural heading
- Pattern observations indicate this page range is noise
- It duplicates a nearby ToC entry title (Part/Section titles often repeat as running headers on subsequent pages)

CRITICAL - Running Header Detection:
Part and section titles commonly appear as running headers at the top of pages AFTER their initial occurrence.
If a heading matches or closely matches a PRECEDING ToC entry title (especially Parts), it's almost certainly a running header, NOT a new chapter.
Look for: Same or similar text appearing on multiple consecutive pages after a Part/Section start.

Use the pattern observations to guide your decision - they provide context about what's real structure vs noise in this specific book.
"""


def build_evaluation_prompt(candidate, observations, toc_context, nearby_toc_entries=""):
    """Build user prompt for evaluating a candidate heading."""

    obs_text = "\n".join(f"- {obs}" for obs in observations) if observations else "No specific observations"

    # Build nearby ToC entries section for running header detection
    nearby_section = ""
    if nearby_toc_entries:
        nearby_section = f"""

## Nearby ToC Entries (CHECK FOR DUPLICATES!)
{nearby_toc_entries}
⚠️ If this candidate's heading text matches or is very similar to a PRECEDING ToC entry, it's likely a RUNNING HEADER, not a new chapter."""

    return f"""## Pattern Observations
{obs_text}

## ToC Context
{toc_context}{nearby_section}

## Candidate to Evaluate
- Page: {candidate.scan_page}
- Heading text: "{candidate.heading_text}"
- Detected level: {candidate.heading_level}
- Preceding ToC entry page: {candidate.preceding_toc_page}
- Following ToC entry page: {candidate.following_toc_page}

Look at the page image. Is this heading a real structural element that belongs in the enriched ToC?
Remember: If this heading matches a nearby ToC entry title (especially preceding), it's a running header - EXCLUDE it."""


def build_missing_search_prompt(missing, page_num):
    """Build user prompt for searching for a missing candidate heading."""

    return f"""## Missing Heading Search

Looking for: "{missing.identifier}"
Searching page: {page_num}
Predicted range: pages {missing.predicted_page_range[0]} to {missing.predicted_page_range[1]}
Confidence: {missing.confidence}

Why we expect this heading:
{missing.reasoning}

Look at the page image. Does the heading "{missing.identifier}" (or a variation like "Chapter {missing.identifier}") appear on this page?"""
