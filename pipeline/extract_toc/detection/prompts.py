"""Prompts for Detection: Direct ToC Entry Extraction"""

SYSTEM_PROMPT = """<role>
You are a Table of Contents extraction specialist.
Your task is to extract structured ToC entries directly from each page.
</role>

<critical_instructions>
You have TWO sources of information:
1. **VISUAL LAYOUT** (image): Shows hierarchy through indentation, styling, positioning
2. **CLEAN OCR TEXT**: Accurate text extraction (use this for entry content)

Your goal: Extract complete ToC entries (title + page number + hierarchy level) in a single pass.

HIERARCHY DETERMINATION:
- Use VISUAL CUES (indentation, styling, size) to determine entry level
- Level 1: Top-level entries (flush left or minimally indented, often bold/large)
- Level 2: Nested entries (moderate indent, sub-entries under Level 1)
- Level 3: Deeply nested entries (deeper indent, sub-entries under Level 2)

Use OCR text for WHAT (the content), use IMAGE for WHERE and HOW (the structure).
</critical_instructions>"""


def build_user_prompt(
    page_num: int,
    total_toc_pages: int,
    ocr_text: str,
    structure_notes: str = None,
    global_structure: dict = None
) -> str:
    """
    Build user prompt for direct ToC entry extraction.

    Args:
        page_num: Current page number
        total_toc_pages: Total number of ToC pages
        ocr_text: Clean OCR text from olm-ocr stage
        structure_notes: Optional page-specific structural observations from find-toc stage
        global_structure: Optional global structure summary from find-toc stage

    Returns:
        Formatted prompt string
    """

    prompt = f"""<task>
Extract ALL Table of Contents entries from this page (page {page_num} of {total_toc_pages}).

You have TWO sources of information:
1. **The IMAGE**: Shows visual layout, indentation, hierarchy, styling
2. **OCR TEXT**: Clean text extraction (more accurate than reading image directly)

<ocr_text>
{ocr_text}
</ocr_text>
"""

    if global_structure:
        prompt += f"""
<global_structure>
The find-toc agent analyzed the ENTIRE ToC and identified this global hierarchy:

Total levels: {global_structure.get('total_levels', 'unknown')}

"""
        level_patterns = global_structure.get('level_patterns', {})
        for level, pattern in sorted(level_patterns.items()):
            prompt += f"""Level {level}:
  - Visual: {pattern.get('visual', 'N/A')}
  - Numbering: {pattern.get('numbering') or 'None'}
  - Has page numbers: {pattern.get('has_page_numbers')}

"""
        consistency_notes = global_structure.get('consistency_notes', [])
        if consistency_notes:
            prompt += "Consistency notes:\n"
            for note in consistency_notes:
                prompt += f"  - {note}\n"

        prompt += """
CRITICAL: Use this global structure to determine hierarchy levels consistently.
- Match visual characteristics (indentation, styling) to the level patterns above
- Verify numbering schemes match expected patterns per level
- Check if page numbers are present/absent as expected per level

This ensures consistent level assignment even if this page only shows a subset of levels.
</global_structure>
"""

    if structure_notes:
        prompt += f"""
<page_specific_notes>
Find-toc observations for this specific page:
{structure_notes}

These page-specific notes complement the global structure above.
</page_specific_notes>
"""

    prompt += """
</task>

<extraction_guidelines>

**WHAT TO EXTRACT**:
Each ToC entry has:
- Title: entry text (may span multiple lines)
- Level: hierarchy depth (1, 2, or 3) determined by visual indentation/styling
- Entry number: if present ("5", "II", "A", "1.1")
- Page number: if present (right-aligned: "127", "ix", "xii")

**HOW VISUAL LAYOUT DETERMINES HIERARCHY**:

Level 1 (Top-level):
- Flush left or minimal indentation (~0-20px from left margin)
- Often **bold** or **larger font**
- Top-level structural divisions
- Examples: "Introduction", "Part I", "Chapter 1: The Beginning"

Level 2 (Nested):
- Moderate indentation (~20-60px from left margin)
- Sub-entries under a Level 1 entry
- Visually nested under previous Level 1 entry
- Examples: "Background", "1.1 Early Period", "Section A"

Level 3 (Deeply nested):
- Deep indentation (~60-100px from left margin)
- Sub-entries under a Level 2 entry
- Further nested detail
- Examples: "Historical Context", "1.1.1 Specific Topic", "Subsection i"

**VISUAL SIGNS TO DETECT**:
✓ **Indentation**: Distance from left edge determines level
✓ **Styling**: Bold/large = higher level (usually Level 1)
✓ **Vertical alignment**: Entries at same indent = same level
✓ **Page numbers**: Right-aligned numbers (may be roman numerals or arabic)
✓ **Parent entries**: Some entries have NO page number (parent of children below)
✓ **Continuations**: Entry title may span multiple lines (same indentation)

**SPECIAL CASES**:

Continuation entries (title spans multiple lines):
```
Chapter 1: An Incredibly Long Title That
           Continues on the Next Line ... 15
```
Merge into single entry: title="Chapter 1: An Incredibly Long Title That Continues on the Next Line"

Parent entries without page numbers:
```
Part I: The Ancient World
  Early Civilizations ... 1
  Classical Period ... 25
```
"Part I" is Level 1 with no page number, children are Level 2

</extraction_guidelines>

<generic_pattern_examples>
# These are GENERIC patterns to teach structure recognition (NOT from any specific book)

Pattern 1: Flat chapter list
```
Introduction ........................... ix
Chapter 1: Early Days .................. 1
Chapter 2: Middle Period ............... 45
Chapter 3: Modern Times ................ 89
```
All Level 1 entries (flush left, same indentation)

Pattern 2: Two-level hierarchy
```
The Beginning .......................... 1
  Background ........................... 3
  Context .............................. 12
The Middle ............................. 25
  Developments ......................... 27
```
Top entries are Level 1 (flush left), nested are Level 2 (indented)

Pattern 3: Parent entries without page numbers
```
Part I: Ancient World
  Origins .............................. 1
  Growth ............................... 20
Part II: Medieval Period
  Decline .............................. 45
  Revival .............................. 70
```
Parts are Level 1 (no page numbers), sub-entries are Level 2 (with page numbers)

Pattern 4: Deep hierarchy
```
1. Major Topic ......................... 1
   1.1 Subtopic ........................ 5
       1.1.1 Detail .................... 7
       1.1.2 More Detail ............... 10
   1.2 Another Subtopic ................ 15
2. Next Major Topic .................... 25
```
Three levels: 1 (flush), 2 (moderate indent), 3 (deep indent)

</generic_pattern_examples>

<text_processing>

**ENTRY NUMBER & TITLE EXTRACTION**:
- Use OCR text for accurate content
- Merge continuation lines (same indentation)
- Extract entry_number if present (before the title)
  - "1. Introduction" → entry_number="1", title="Introduction"
  - "Chapter 5: The End" → entry_number="5", title="The End"
  - "Part II: Ancient World" → entry_number="II", title="Ancient World"
  - "1.1 Background" → entry_number="1.1", title="Background"
  - "Appendix A: Notes" → entry_number="A", title="Notes"
  - "Foreword" → entry_number=null, title="Foreword"

**LEVEL NAME DETECTION**:
- Detect semantic type from text patterns
  - Contains "Volume" → level_name="volume"
  - Contains "Book" (as division) → level_name="book"
  - Contains "Part" → level_name="part"
  - Contains "Unit" → level_name="unit"
  - Contains "Chapter" → level_name="chapter"
  - Contains "Section" → level_name="section"
  - Contains "Subsection" → level_name="subsection"
  - Contains "Act" → level_name="act"
  - Contains "Scene" → level_name="scene"
  - Contains "Appendix" → level_name="appendix"
  - No clear type → level_name=null

**PAGE NUMBER EXTRACTION**:
- Extract right-aligned text that looks like a page number
- Preserve exactly as shown: "ix", "XII", "23"
- Empty if no page number (parent entries)

**CAPITALIZATION NORMALIZATION**:
- Convert ALL CAPS titles to Title Case:
  - "FOREWORD" → "Foreword"
  - "THE OPENING CHAPTER" → "The Opening Chapter"
- Preserve proper nouns: "Part I", "Book II", "World War II"

</text_processing>

<output_requirements>
Return JSON with this structure:
{
    "entries": [
        {
            "entry_number": "5" or "II" or "1.1" or null,
            "title": "Introduction",
            "level": 1,
            "level_name": "volume" or "book" or "part" or "unit" or "chapter" or "section" or "subsection" or "act" or "scene" or "appendix" or null,
            "printed_page_number": "1" or null
        }
    ],
    "page_metadata": {
        "continuation_from_previous": false,
        "continues_to_next": true,
        "total_entries_on_page": 15
    },
    "confidence": 0.95,
    "notes": "Any observations about this page's structure or challenges"
}

CRITICAL REQUIREMENTS:
- "level" (REQUIRED) MUST be 1, 2, or 3 (visual hierarchy)
- "title" (REQUIRED) must be non-empty
- "entry_number" (optional) is string: "5", "II", "A", "1.1", or null
- "level_name" (optional) is string: "volume", "book", "part", "unit", "chapter", "section", "subsection", "act", "scene", "appendix", or null
- "printed_page_number" (optional) is string or null
- Extract entries in the ORDER they appear on the page (top to bottom)
- Each entry should be COMPLETE (don't output partial entries)

</output_requirements>

Begin extraction."""

    return prompt
