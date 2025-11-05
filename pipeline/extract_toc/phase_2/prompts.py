"""Prompts for Phase 1: Direct ToC Entry Extraction"""

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
- Level 1: Chapters/Parts (flush left or minimally indented, often bold/large)
- Level 2: Sections (moderate indent, sub-entries under chapters)
- Level 3: Subsections (deeper indent, sub-entries under sections)

Use OCR text for WHAT (the content), use IMAGE for WHERE and HOW (the structure).
</critical_instructions>"""


def build_user_prompt(
    page_num: int,
    total_toc_pages: int,
    ocr_text: str,
    structure_notes: str = None
) -> str:
    """
    Build user prompt for direct ToC entry extraction.

    Args:
        page_num: Current page number
        total_toc_pages: Total number of ToC pages
        ocr_text: Clean OCR text from ocr-pages stage
        structure_notes: Optional structural observations from find-toc stage

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

    if structure_notes:
        prompt += f"""
<structure_observations>
The find-toc agent observed these structural patterns in the ToC:
{structure_notes}

Use these observations to guide your analysis (but trust the visual evidence if patterns vary by page).
</structure_observations>
"""

    prompt += """
</task>

<extraction_guidelines>

**WHAT TO EXTRACT**:
Each ToC entry typically has:
- Title (chapter/section name, may span multiple lines)
- Printed page number (right-aligned: "127", "ix", "xii")
- Hierarchy level (determined by visual indentation/styling)
- Optional chapter number (if present in title: "1.", "Chapter 5", "Part II")

**HOW VISUAL LAYOUT DETERMINES HIERARCHY**:

Level 1 (Chapters/Parts):
- Flush left or minimal indentation (~0-20px from left margin)
- Often **bold** or **larger font**
- Top-level structural divisions
- Examples: "Chapter 1: Introduction", "Part I", "Foreword"

Level 2 (Sections):
- Moderate indentation (~20-60px from left margin)
- Sub-entries under a Level 1 chapter
- Visually nested under previous Level 1 entry
- Examples: "1.1 Background", "Early Period"

Level 3 (Subsections):
- Deep indentation (~60-100px from left margin)
- Sub-entries under a Level 2 section
- Further nested detail
- Examples: "1.1.1 Historical Context", "Specific Topic"

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
  Chapter 1: Early Civilizations ... 1
  Chapter 2: Classical Period ... 25
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

Pattern 2: Chapters with sections
```
Chapter 1: The Beginning ............... 1
  Section 1.1: Background .............. 3
  Section 1.2: Context ................. 12
Chapter 2: The Middle .................. 25
  Section 2.1: Developments ............ 27
```
Chapters are Level 1 (flush left), Sections are Level 2 (indented)

Pattern 3: Parts with chapters
```
Part I: Ancient World
  Chapter 1: Origins ................... 1
  Chapter 2: Growth .................... 20
Part II: Medieval Period
  Chapter 3: Decline ................... 45
  Chapter 4: Revival ................... 70
```
Parts are Level 1 (no page numbers), Chapters are Level 2 (with page numbers)

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

**TITLE EXTRACTION**:
- Use OCR text for accurate content
- Merge continuation lines (same indentation)
- Strip chapter numbers from title if present
  - "1. Introduction" → title="Introduction", chapter_number=1
  - "Chapter Five: The End" → title="The End", chapter_number=5

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
            "chapter_number": 1 or null,
            "title": "Introduction",
            "printed_page_number": "1" or null,
            "level": 1
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
- "level" MUST be 1, 2, or 3
- "title" is REQUIRED and must be non-empty
- "chapter_number" is optional (null if not present in text)
- "printed_page_number" is optional (null for parent entries without page numbers)
- Extract entries in the ORDER they appear on the page (top to bottom)
- Each entry should be COMPLETE (don't output partial entries)

</output_requirements>

Begin extraction."""

    return prompt
