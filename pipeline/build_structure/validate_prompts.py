"""
Boundary verification prompts for validation.
"""


def build_chapter_verification_prompt(expected_title: str, page_text: str) -> str:
    """
    Build prompt for verifying chapter boundaries.

    Args:
        expected_title: Expected chapter title from draft metadata
        page_text: Text content from the page to verify

    Returns:
        Formatted prompt string
    """
    return f"""You are verifying whether a page from a scanned book is the start of a new chapter.

Expected chapter title: "{expected_title}"

Page text (first 1500 chars):
{page_text[:1500]}

Does this page START a new chapter?
- Look for chapter headings, titles, or clear chapter markers
- The expected title is "{expected_title}" but it might be formatted differently
- Some chapters start with "CHAPTER 1", "Part I", roman numerals, etc.

Respond with JSON:
{{
  "is_boundary": true/false,
  "detected_title": "exact title text from page" or null if not a chapter start,
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation"
}}"""


def build_section_verification_prompt(expected_title: str, page_text: str) -> str:
    """
    Build prompt for verifying section boundaries.

    Args:
        expected_title: Expected section title from draft metadata
        page_text: Text content from the page to verify

    Returns:
        Formatted prompt string
    """
    return f"""You are verifying whether a page from a scanned book contains a section heading.

Expected section title: "{expected_title}"

Page text (first 1500 chars):
{page_text[:1500]}

Does this page contain a section heading?
- Look for section headings, subheadings, or subsection markers
- The expected title is "{expected_title}" but it might be formatted differently
- Sections are typically less prominent than chapter headings
- Sections may appear mid-page, not necessarily at the top

Respond with JSON:
{{
  "is_boundary": true/false,
  "detected_title": "exact title text from page" or null if no section heading found,
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation"
}}"""
