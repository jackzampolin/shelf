"""Prompts for Phase 3: Element Identification"""

SYSTEM_PROMPT = """You are a Table of Contents structure analyzer.

Your task is to identify individual structural elements (entries) in ToC pages using both:
1. Visual layout from the image
2. Clean OCR text from OlmOCR

Each element represents ONE distinct item in the table of contents."""


def build_user_prompt(
    page_num: int,
    total_toc_pages: int,
    ocr_text: str,
    structure_notes: str = None
) -> str:
    """
    Build user prompt for element identification.

    Args:
        page_num: Current page number
        total_toc_pages: Total number of ToC pages
        ocr_text: Clean OCR text from Phase 2
        structure_notes: Optional notes from Phase 1 finder

    Returns:
        Formatted prompt string
    """

    prompt = f"""<task>
Analyze this Table of Contents page (page {page_num} of {total_toc_pages}) and identify ALL structural elements.

You have TWO sources of information:
1. **The IMAGE**: Shows visual layout, indentation, hierarchy, styling
2. **OCR TEXT**: Clean text extraction (more accurate than reading image directly)

<ocr_text>
{ocr_text}
</ocr_text>
"""

    if structure_notes:
        prompt += f"""
<structure_notes>
{structure_notes}
</structure_notes>
"""

    prompt += """
</task>

<element_definition>
A "structural element" is ONE of:
- **Chapter/Part title** (often without page number, larger/bold)
- **Section heading** (hierarchical grouping)
- **Entry with page number** (title + page number)
- **Continued entry** (continuation from previous page)

Each element should capture:
- The full text (from OCR)
- Visual position (x, y coordinates on image for reference)
- Indentation level (0=top-level, 1=indented once, 2=indented twice, etc.)
- Type (chapter/section/entry/continuation)
</element_definition>

<instructions>
1. **Use OCR text for accuracy** - Don't re-read the text from the image
2. **Use image for structure** - Visual layout shows hierarchy better than text alone
3. **Match OCR lines to visual positions** - Map each OCR line to its position on the page
4. **Preserve hierarchy** - Indentation level determines parent-child relationships
5. **Handle continuations** - Note when entries span multiple lines or pages
</instructions>

<output_requirements>
Return JSON with this structure:
{
    "elements": [
        {
            "text": "exact text from OCR",
            "visual_x": 100,
            "visual_y": 50,
            "indentation_level": 0,
            "type": "chapter|section|entry|continuation",
            "has_page_number": true,
            "page_number": "123",
            "notes": "any structural observations"
        }
    ],
    "page_structure": {
        "columns": 1,
        "has_parent_entries": true,
        "continuation_from_previous": false,
        "continues_to_next": true
    },
    "confidence": 0.95,
    "notes": "overall observations about this page's structure"
}
</output_requirements>

Begin analysis."""

    return prompt
