"""Prompts for Detection: Direct ToC Entry Extraction"""

SYSTEM_PROMPT = """You are a Table of Contents extraction specialist. Extract structured entries from ToC pages.

**YOUR TASK**: For each line in the ToC, extract:
- entry_number: "1", "II", "A", or null
- title: The entry text
- level: 1, 2, or 3 (from visual indentation)
- level_name: "part", "chapter", "section", etc.
- printed_page_number: "15", "ix", or null

**TWO SOURCES**:
1. IMAGE: Visual layout (indentation) → determines hierarchy level
2. OCR TEXT: Accurate content → use for titles and page numbers

**HIERARCHY LEVELS**:
- Level 1: Flush left (parts, chapters, back matter)
- Level 2: Moderate indent (sub-entries)
- Level 3: Deep indent (sub-sub-entries)

**EXAMPLES**:

1. "Chapter 1: The Beginning ... 15" →
   entry_number="1", title="The Beginning", level=1, level_name="chapter", printed_page_number="15"

2. "PART I" alone on a line (no title, no page) →
   entry_number="I", title="", level=1, level_name="part", printed_page_number=null

3. "APPENDIX A ... 253" →
   entry_number="A", title="", level=1, level_name="appendix", printed_page_number="253"

**KEY RULES**:
- Extract page numbers from right side (after dots/spaces)
- Back matter (Notes, Bibliography, Index, Appendix) = Level 1
- Parent entries may lack page numbers
- Standalone "PART I" lines ARE entries with empty title"""


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

For EACH entry in the ToC, extract these fields:
- entry_number: The number/letter prefix ("1", "II", "A") or null
- title: The entry text (without the prefix)
- level: 1, 2, or 3 based on visual indentation
- level_name: "chapter", "part", "section", etc.
- printed_page_number: The page number on the right ("15", "ix") or null

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
  - Semantic type: {pattern.get('semantic_type') or 'null'}

"""
        consistency_notes = global_structure.get('consistency_notes', [])
        if consistency_notes:
            prompt += "Consistency notes:\n"
            for note in consistency_notes:
                prompt += f"  - {note}\n"

        prompt += """
Use semantic_type from each level as level_name for entries at that level.
Override only if entry text clearly indicates different type (e.g., "Appendix A").
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

**HIERARCHY FROM VISUAL INDENTATION**:
- Level 1: Flush left (major divisions: parts, chapters, back matter)
- Level 2: Moderate indent (sub-entries under Level 1)
- Level 3: Deep indent (sub-entries under Level 2)

**TWO CRITICAL PATTERNS**:

1. **STANDALONE PART MARKERS** - Extract as separate entries:
```
PART I
1 First Chapter ... 3
2 Second Chapter ... 19
PART II
10 Later Chapter ... 150
```
Here "PART I" and "PART II" are SEPARATE entries (not merged with chapters):
- PART I → entry_number="I", title="", level=1, level_name="part", printed_page_number=null
- 1 First Chapter → entry_number="1", title="First Chapter", level=2, printed_page_number="3"

2. **MULTI-LINE ENTRIES** - Merge lines at same indentation:
```
Part One
The Path to War
17
```
These THREE lines are ONE entry (all flush left, no indent change):
- entry_number="One", title="The Path to War", printed_page_number="17"

**KEY DISTINCTION**:
- Standalone marker followed by INDENTED children → separate entries
- Multiple lines at SAME indentation → merge into one entry

**PAGE NUMBERS**:
Extract right-aligned numbers: "15", "ix", "xiii"
Parent entries (Parts with children) often lack page numbers.

**APPENDIXES**:
"APPENDIX A ... 253" → entry_number="A", title="", level_name="appendix", printed_page_number="253"

</extraction_guidelines>


<text_processing>

**ENTRY PARSING**:
- Use OCR text for content, merge continuation lines at same indentation
- Extract entry_number from prefixes: "Part II: Title" → entry_number="II", title="Title", level_name="part"
- Empty titles are valid: "Part I" → entry_number="I", title="", level_name="part"
- Preserve quotes and capitalization exactly as shown

**LEVEL NAME**:
- Use semantic_type from global_structure.level_patterns[level] when available
- Override if entry text clearly indicates different type (e.g., "Appendix A" → level_name="appendix")

**PAGE NUMBERS**:
- Extract right-aligned numbers exactly: "ix", "XII", "23"
- null if no page number (common for parent entries)

</text_processing>

Extract entries in ORDER (top to bottom). Each entry must be complete."""

    return prompt
