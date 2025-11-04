"""Prompts for Phase 3: Element Identification"""

SYSTEM_PROMPT = """<role>
You are a Table of Contents structure analyzer.
Your task is to identify individual structural elements (entries) in ToC pages.
</role>

<critical_instructions>
You have TWO sources of information:
1. **VISUAL LAYOUT** (image): Shows hierarchy, indentation, styling
2. **CLEAN OCR TEXT**: Accurate text extraction (use this for content)

POSITION TELLS YOU EVERYTHING:
- Y-coordinate = which row (elements on same line group together)
- X-coordinate = indentation level (hierarchy)
- Visual styling = type (bold/large = chapter, indented = section)

Use OCR for WHAT (the text), use IMAGE for WHERE (the structure).
</critical_instructions>"""


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

<visual_detection>
WHAT TO IDENTIFY:
✓ Entry numbers (chapter/part numbers: "1.", "Chapter 5", "Part II")
✓ Entry titles (chapter/section names, may span multiple lines)
✓ Page numbers (usually right-aligned: "127", "ix", "xii")
✓ Hierarchical elements (indented sub-entries)

HOW INDENTATION DETERMINES HIERARCHY:
- Flush left (0 indent) = Top-level chapter/part
- Small indent (~20-40px) = Section under chapter
- Larger indent (~40-80px) = Subsection

VISUAL SIGNS OF STRUCTURE:
- **Bold/Large text** = Chapter/Part heading
- **Aligned vertically** = Same hierarchy level
- **Indented** = Child of previous un-indented entry
- **Right-aligned numbers** = Page numbers
- **No page number** = Parent entry (has children below)
</visual_detection>

<pattern_examples>
# Generic patterns (NOT from any specific book)

Pattern 1: Flat list
```
0px indent: "Introduction" → page "ix"
0px indent: "Chapter 1" → page "1"
0px indent: "Chapter 2" → page "25"
```
All indentation_level=0, all type="entry"

Pattern 2: Hierarchy with parent entries
```
0px indent: "Part I" (NO page number) → parent
  20px indent: "Early Period" → page "1"
  20px indent: "Middle Era" → page "45"
0px indent: "Part II" (NO page number) → parent
  20px indent: "Modern Times" → page "90"
```
Part I/II: indentation_level=0, type="section", has_page_number=false
Children: indentation_level=1, type="entry", has_page_number=true

Pattern 3: Deep nesting
```
0px indent: "Section A"
  20px indent: "Topic 1" → page "10"
    40px indent: "Subtopic 1a" → page "12"
    40px indent: "Subtopic 1b" → page "18"
  20px indent: "Topic 2" → page "25"
```
Levels: 0 (Section A), 1 (Topics), 2 (Subtopics)
</pattern_examples>

<instructions>
1. **Match OCR text to visual position** - Find each OCR line on the image
2. **Measure indentation** - How far from left edge? (visual_x value)
3. **Determine hierarchy** - Compare indentations to assign levels (0, 1, 2)
4. **Identify type** - Based on styling, indentation, presence of page number
5. **Extract page numbers** - Right-side text that looks like a page number
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
