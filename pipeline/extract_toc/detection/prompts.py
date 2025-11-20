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
Levels are determined by VISUAL INDENTATION and STYLING, verified against global structure.

**Step 1: Measure Visual Position**
- Level 1: Flush left (0-20px from margin) OR largest/boldest text
- Level 2: Moderate indent (20-60px from margin)
- Level 3: Deep indent (60-100px from margin)

**Step 2: Cross-reference with Global Structure**
If global_structure is provided, use it to verify your level assignment:
- Does the indentation match the expected pattern for this level?
- Does the numbering scheme match (Roman vs Arabic vs null)?
- Does this level typically have page numbers?

**Step 3: Verify Semantic Consistency**
Level assignment should be semantically coherent:
- Level 1: Major divisions (parts, books, units, top chapters)
- Level 2: Subdivisions (chapters under parts, sections under chapters)
- Level 3: Fine details (subsections, appendices)

**SPECIAL RULE: Endmatter is Always Level 1**
Back matter sections default to Level 1 regardless of visual appearance:
- Notes, Footnotes, Endnotes
- Bibliography, References, Sources
- Index, Indices
- Appendix, Appendices (when at end)
- Acknowledgments, Credits
- Glossary, Abbreviations

Rationale: These are structural divisions of the book, not hierarchical content.
Even if they appear visually similar to nested entries, treat as Level 1.

**WARNING: Common Pitfall - Multi-line Entries**

DO NOT assign different levels to lines within the same entry:
```
Part I                    <-- NOT level 1
The Opening Period        <-- NOT level 2
I                         <-- This is all ONE entry at level 1!
```

If lines have NO indentation difference → Same entry, not parent/child.

**Decision Tree:**

1. Are the lines at DIFFERENT indentations?
   - YES → Different levels (parent/child relationship)
   - NO → Continue to step 2

2. Is there a page number separating the lines?
   - YES → Multi-line entry (merge into one)
   - NO → Check if first line is structural prefix

3. Is first line just "Part I" / "BOOK II" with no other text?
   - YES → Check next line's indentation
     - Indented? → Separate parent entry (level 1) + children (level 2)
     - Same indent? → Prefix for merged entry (level 1)
   - NO → Multi-line entry (merge into one)

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

**ENFORCE GLOBAL STRUCTURE CONSISTENCY**:

The global structure summary is the AUTHORITATIVE source for level patterns.

Before assigning a level to an entry:
1. Check global_structure.total_levels - Your extraction MUST match this count
2. Check global_structure.level_patterns[level] - Match visual + numbering + page_numbers
3. If your visual analysis conflicts with global structure, RE-EXAMINE the image

Example conflict resolution:
- You see: "Part I" on one line, "Topic Title" on next line, both flush left
- Global structure says: total_levels=1 (flat structure, no hierarchy)
- RESOLUTION: Merge into single level 1 entry, don't create parent/child

WHY: The find-toc agent analyzed ALL pages and determined overall structure.
Single-page analysis can be ambiguous, but global view is definitive.

If total_levels=1 → Extract ONLY level 1 entries (no level 2 or 3)
If total_levels=2 → Use BOTH level 1 and level 2 (match indentation patterns)
If total_levels=3 → Use all three levels (match indentation patterns)

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

Multi-line entries with separated page numbers:
Some ToCs have page numbers on a separate line BELOW the title:
```
Part I
A Long Descriptive Title About
the Subject Matter
15                        <-- Page number on separate line
```

Recognition pattern:
- Title text spans 1-3 lines at same indentation
- Next line contains ONLY a number/Roman numeral (page reference)
- NO indentation change between lines

Merge into single entry:
- entry_number: Extract from first line if present ("I" from "Part I")
- title: Combine all text lines (exclude first line if it's just "Part I")
- printed_page_number: The isolated number on last line
- level: Based on indentation of the ENTIRE block (not each line)

Example:
```
Part I
The Early Period
I
```
→ entry_number="I", title="The Early Period", page="I", level=1

CONTRAST with hierarchical structure:
```
Part I: The Ancient Era
  Origins ... 1           <-- Indented child
  Growth ... 20
```
→ Entry 1: title="Part I: The Ancient Era", page=null, level=1 (parent)
→ Entry 2: entry_number=null, title="Origins", page="1", level=2 (child)

The key difference: INDENTATION indicates hierarchy, not line breaks.

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

**CRITICAL: PREFIX PARSING RULES**:

Structural prefixes (Part, Book, Unit, Volume, Act) should be parsed as entry_number, NOT title:

Pattern: "Part I: Title Text" or "BOOK II: Title Text"
- entry_number="I" (or "II", etc.)
- title="Title Text" (WITHOUT the prefix)
- level_name="part" (or "book", etc.)

**NEVER include the prefix in the title field:**
❌ WRONG: title="Part I: The Beginning"
✅ CORRECT: entry_number="I", title="The Beginning"

❌ WRONG: title="BOOK III: The Middle Years"
✅ CORRECT: entry_number="III", title="The Middle Years"

Examples:
- "Part I: The Beginning" → entry_number="I", title="The Beginning", level_name="part"
- "BOOK III: The Middle Years" → entry_number="III", title="The Middle Years", level_name="book"
- "Unit 2: Foundation Concepts" → entry_number="2", title="Foundation Concepts", level_name="unit"
- "Part One: Early Period" → entry_number="One", title="Early Period", level_name="part"
- "Volume IV" → entry_number="IV", title="", level_name="volume"
- "Book II" → entry_number="II", title="", level_name="book"

**How to parse:**
1. Identify prefix keyword: Part, Book, Unit, Volume, Act
2. Extract number: Roman (I, II), Arabic (1, 2), or Spelled (One, Two)
3. Extract title: Everything AFTER the colon (or empty if no colon)
4. Set level_name based on prefix keyword

CRITICAL: Detect and preserve numbering patterns:
- Roman numerals: I, II, III, IV, V, etc.
- Arabic numerals: 1, 2, 3, 4, 5, etc.
- Spelled out: One, Two, Three, Four, Five, etc.
- The pattern used is part of the book's structure - preserve it exactly

EMPTY TITLES ARE VALID:
If the entry is just a structural prefix with NO additional text:
- "Part I" → entry_number="I", title="", level_name="part"
- "BOOK II" → entry_number="II", title="", level_name="book"
- "Volume III" → entry_number="III", title="", level_name="volume"

This is completely fine - the entry_number and level_name provide the structure.
Do NOT try to invent a title if there isn't one.

ONLY treat prefix as separate parent entry if:
1. Prefix appears on separate line with NO title text following
2. AND next entries are clearly INDENTED (children under parent)
3. AND prefix line has NO page number

Example of separate parent entry:
```
Part I                         <-- No title, no page, no indent
  Chapter 1: Topic A ... 10    <-- Clearly indented children
  Chapter 2: Topic B ... 20
```
→ Entry 1: title="Part I", level=1, page=null (parent)
→ Entry 2: entry_number="1", title="Topic A", level=2, page="10" (child)

SPECIAL CASE: Multi-line entries with page number on separate line:
```
Part I
The Opening Period
I                         <-- Page number on its own line
```

This is a SINGLE entry split across 3 lines:
- entry_number="I" (from "Part I")
- title="The Opening Period"
- printed_page_number="I" (Roman numeral)
- level=1 (NOT level 2 - no hierarchy here)

KEY DECISION RULE:
- If no visual indentation difference → merge into single entry
- If clear indentation difference → separate parent/child entries

**PAGE NUMBER EXTRACTION**:
- Extract right-aligned text that looks like a page number
- Preserve exactly as shown: "ix", "XII", "23", "I", "1"
- Empty if no page number (parent entries)

**QUOTE PRESERVATION**:
- Preserve surrounding quotes in titles EXACTLY as shown
  - '"A sort of wartime normal"' → '"A sort of wartime normal"' (keep quotes)
  - "The Beginning" → "The Beginning" (no quotes to add)
- Do NOT strip or normalize quotes
- Rationale: Quotes may indicate direct quotations or stylistic emphasis

**CAPITALIZATION PRESERVATION**:
- Preserve original capitalization EXACTLY as shown in the OCR text
  - "FOREWORD" → "FOREWORD" (keep all caps)
  - "The Opening Chapter" → "The Opening Chapter" (keep mixed case)
  - "foreword" → "foreword" (keep lowercase)
- Do NOT normalize or convert capitalization
- Rationale: Capitalization may carry semantic meaning (emphasis, styling)

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
