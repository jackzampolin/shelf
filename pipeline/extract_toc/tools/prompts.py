TOC_STRUCTURE_DETECTION_PROMPT = """<role>
You are a document observer. Describe what you SEE in these ToC pages WITHOUT reasoning or making predictions.
</role>

<task>
Look at ALL ToC pages together and describe the VISUAL PATTERNS you observe:
- How many entries do you see? (approximate count, e.g., "20-25 entries")
- What numbering style? (Roman numerals? Arabic? "Chapter X"? None?)
- How many indentation levels?
- What formatting patterns? (leader dots? page numbers right-aligned?)
- Any unusual features?

DO NOT:
- Detect gaps (just describe what you SEE)
- Predict expected ranges (don't guess "I-XV", just say "Roman numerals")
- Count exact entries (estimates like "~20" are fine)
- Reason about completeness (just observe)
</task>

<what_to_observe>
**Visual structure:**
- Approximate number of entries visible
- Vertical spacing patterns (consistent? varied?)
- Indentation levels (flush left, indented once, indented twice)

**Numbering patterns you see:**
- Roman numerals (I, II, III...)?
- Arabic numerals (1, 2, 3...)?
- "Chapter" prefix (Chapter 1, Chapter 2...)?
- No numbers (just titles)?
- Mixed (some numbered, some not)?

**Layout features:**
- Leader dots between titles and page numbers?
- Page numbers right-aligned?
- Bold/larger text for certain entries?
- Parts/sections visible?

**Formatting observations:**
- All entries follow same visual pattern?
- Different formatting for different levels?
- Any unusual spacing or breaks?
</what_to_observe>

<output_schema>
Return JSON with your observations:

{
  "visual_observations": {
    "approximate_entry_count": "20-25 entries",
    "numbering_style": "roman_numerals",
    "indentation_levels": 2,
    "formatting_notes": [
      "Leader dots connect titles to page numbers",
      "Page numbers right-aligned",
      "Some entries indented (sections under chapters)"
    ],
    "structural_features": [
      "Vertical list with consistent spacing",
      "Two-column layout (titles left, numbers right)"
    ]
  },
  "confidence": 0.95,
  "notes": ["Clear visual structure", "All entries visible"]
}

**Field descriptions:**
- approximate_entry_count: Rough count (e.g., "15-20", "30-35", "~25")
- numbering_style: What you see ("roman_numerals", "arabic_numerals", "chapter_prefix", "mixed", "none")
- indentation_levels: How many levels (1, 2, or 3)
- formatting_notes: List of visual formatting you observe
- structural_features: Overall layout observations
- confidence: 0.0-1.0 based on image clarity
- notes: Any concerns or ambiguities
</output_schema>

<output_requirements>
Return ONLY valid JSON.
No markdown code fences.
No explanatory text.
</output_requirements>"""


# Phase 3: Extraction with self-verification
def build_detail_extraction_prompt(structure_overview: dict) -> str:
    """
    Build Phase 3 prompt with observations from Phase 2.

    Args:
        structure_overview: Observations from Phase 2

    Returns:
        Formatted prompt for extraction + self-verification
    """
    approx_count = structure_overview.get('approximate_entry_count', 'unknown')
    numbering_style = structure_overview.get('numbering_style', 'unknown')
    indentation_levels = structure_overview.get('indentation_levels', 'unknown')
    formatting_notes = structure_overview.get('formatting_notes', [])

    formatting_bullets = "\n".join(f"- {note}" for note in formatting_notes) if formatting_notes else "- (no specific notes)"

    return f"""<role>
You are a Table of Contents extractor. Extract ALL entries accurately, then verify completeness.
</role>

<observations_from_phase2>
From visual analysis, this ToC has:
- **Approximate count:** {approx_count}
- **Numbering style:** {numbering_style}
- **Indentation levels:** {indentation_levels}
- **Formatting:**
{formatting_bullets}

These are OBSERVATIONS, not requirements. Extract what you actually see.
</observations_from_phase2>

<extraction_instructions>
You will receive:
1. IMAGES of the ToC pages (for visual structure)
2. OCR TEXT (for accurate word extraction)
3. ToC page range (scan page numbers)

**Extract using hybrid approach:**
- IMAGES → indentation, hierarchy, entry count, visual layout, multi-line patterns
- OCR TEXT → exact titles, chapter numbers, page numbers
</extraction_instructions>

<pattern_recognition>
**PATTERN 1: Parent entries (Parts/Sections without page numbers)**

Visual signs:
- NO page number visible
- Followed by indented entries that DO have page numbers
- Often styled differently (bold, larger, "Part I", "Section A")

Example OCR:
```
Part I
April 12, 1945 .......... 1
The First Days .......... 15

Part II
The Political Education .......... 39
```

Extraction:
```json
[
  {{"chapter_number": null, "title": "Part I: April 12, 1945", "printed_page_number": "1", "level": 1}},
  {{"chapter_number": null, "title": "The First Days", "printed_page_number": "15", "level": 2}},
  {{"chapter_number": null, "title": "Part II: The Political Education", "printed_page_number": "39", "level": 1}}
]
```

**CRITICAL:** Merge parent header with first child's title. Use child's page number.

**PATTERN 2: Standalone complete entries (one line, has page number)**

Visual signs:
- Clear page number at end of line
- Standalone semantic unit
- May be indented or flush left

Example OCR:
```
Introduction .......... ix
Epilogue .......... 355
Index .......... 423
```

Extraction:
```json
[
  {{"chapter_number": null, "title": "Introduction", "printed_page_number": "ix", "level": 1}},
  {{"chapter_number": null, "title": "Epilogue", "printed_page_number": "355", "level": 1}},
  {{"chapter_number": null, "title": "Index", "printed_page_number": "423", "level": 1}}
]
```

**PATTERN 3: Multi-line titles (long title wraps to next line)**

Visual signs:
- First line: Title start (no page number)
- Second line: Title continuation + page number
- No semantic break, same indentation level
- NOT followed by indented children

Example OCR:
```
The Long and Complicated History of
  the Eastern Campaign .......... 127
```

Extraction:
```json
[
  {{"chapter_number": null, "title": "The Long and Complicated History of the Eastern Campaign", "printed_page_number": "127", "level": 1}}
]
```

**CRITICAL:** Merge wrapped lines into ONE entry. Look for continuation cues (incomplete thought, same indent).

**PATTERN 4: Numbered chapters under parts**

Visual signs:
- Parent: "Part I" or "I" (no page number)
- Children: "Chapter 1", "1.", numbered entries (with page numbers)
- Children are indented

Example OCR:
```
Part I
1. April 12, 1945 .......... 1
2. The First Days .......... 15

Part II
3. The Political Education .......... 39
```

Extraction:
```json
[
  {{"chapter_number": 1, "title": "Part I: April 12, 1945", "printed_page_number": "1", "level": 1}},
  {{"chapter_number": 2, "title": "The First Days", "printed_page_number": "15", "level": 2}},
  {{"chapter_number": 3, "title": "Part II: The Political Education", "printed_page_number": "39", "level": 1}}
]
```

**CRITICAL:** Part number goes in title, Chapter number in chapter_number field.

**HOW TO DISTINGUISH PATTERNS:**

Key signal: **PAGE NUMBERS indicate complete entries**

1. Line WITH page number = likely complete entry (Pattern 2, 3, or child in Pattern 1/4)
2. Line WITHOUT page number = either:
   - Parent (if followed by indented entries WITH page numbers) → Pattern 1 or 4
   - Title continuation (if next line completes the thought) → Pattern 3
   - Standalone rare case (decorative headers, skip these)

3. Use context:
   - If "Part I" followed by titled entries → Pattern 1 or 4 (merge part into first child title)
   - If partial sentence followed by completion → Pattern 3 (merge lines)
   - If standalone entry with page number → Pattern 2 (keep as-is)
</pattern_recognition>

<numbering_extraction>
For numbering style "{numbering_style}":

**Chapter numbering (goes in chapter_number field):**
- "1. Title" → chapter_number=1, title="Title"
- "Chapter 5: Title" → chapter_number=5, title="Title"
- "I. Title" (if Roman = chapters) → chapter_number=1, title="Title"

**Part numbering (goes in title field):**
- "Part I" + "Title .... 1" → title="Part I: Title", chapter_number=null
- "I" + "Title .... 1" (if Roman = parts) → title="Part I: Title", chapter_number=null

**How to tell Part vs Chapter Roman numerals:**
- Context: If followed by indented numbered items (1, 2, 3), it's a Part
- Context: If standalone with page number, it's a Chapter
- Visual: Parts usually larger/bolder, no indentation
- Semantic: "Part I" is explicit, lone "I" requires context

**Title cleanup:**
- NEVER put Part numbers in chapter_number field
- ALWAYS remove chapter prefixes from title ("Chapter 5: Title" → "Title")
- MERGE parent labels into child titles ("Part I" + "April 12" → "Part I: April 12")

**Page numbers (from OCR):**
- Roman numerals: "ix", "xiv" (strings, not integers)
- Arabic numerals: "15", "203" (strings, not integers)
- Missing: null (for parent entries if not merged)
</numbering_extraction>

<hierarchy_detection>
**Level assignment uses BOTH visual indentation AND semantics:**

- Level 1: Top-level entries (Parts, main chapters, front/back matter)
  - Flush left OR merged parent+child
  - Semantic: Major divisions

- Level 2: Sections/sub-chapters
  - Indented once
  - OR children under merged parts
  - Semantic: Subdivisions of level 1

- Level 3: Subsections
  - Indented twice
  - Semantic: Subdivisions of level 2

**When merging parent+child (Pattern 1/4):**
- Use child's visual indentation for level
- If children are flush left, merged entry = level 1
- If children are indented, merged entry = their level


<self_verification>
**CRITICAL: After extraction, verify BEFORE returning:**

1. **Pattern application check:**
   - Did I find any lines WITHOUT page numbers?
   - If yes, did I apply Pattern 1/3/4 (merge with following lines)?
   - Or did I incorrectly create standalone entries with null page numbers?
   - RULE: Every final entry should have a page number (except rare decorative headers to skip)

2. **Part/Chapter distinction check:**
   - Do I have entries like: chapter_number=1, title="Part"?
   - This is WRONG! Part numbers go in title field
   - CORRECT: chapter_number=null, title="Part I: [subtitle]"

3. **Count check:**
   - Phase 2 observed {approx_count}
   - How many did I extract? ___
   - If significantly different (off by 3+), did I:
     * Over-merge? (Pattern 1/4 applied too aggressively)
     * Under-merge? (Missed parent-child relationships)
   - LOOK AGAIN at images to verify

4. **Sequence check (if numbered chapters):**
   - List my chapter numbers: [1, 2, 3, ...]
   - Are there gaps? (e.g., [1, 2, 4, 5] is missing 3)
   - If gaps exist, LOOK AGAIN at images/OCR to find missing entries

5. **Title cleanup check:**
   - Do any titles still have chapter number prefixes? ("1.", "Chapter 5:")
   - If yes, remove them (they should be in chapter_number field)
   - Do merged Part titles include the part label? ("Part I: Title")
   - If no, add it

6. **Page number check:**
   - Are ALL page numbers strings (not integers)?
   - Did I extract them from OCR text accurately?
   - Are there entries with null page numbers that should have been merged?

7. **Boundary check:**
   - Did I check FIRST page for any entries?
   - Did I check LAST page for any entries?
   - Check page breaks (entries spanning pages)

**If ANY check fails → Fix it before returning!**
</self_verification>

<output_schema>
Return JSON with all entries:

{{
  "entries": [
    {{
      "chapter_number": null,
      "title": "Foreword",
      "printed_page_number": "vii",
      "level": 1
    }},
    {{
      "chapter_number": null,
      "title": "Part I: The Ancient World",
      "printed_page_number": "3",
      "level": 1
    }},
    {{
      "chapter_number": 1,
      "title": "Early Civilizations",
      "printed_page_number": "12",
      "level": 2
    }},
    {{
      "chapter_number": 2,
      "title": "The Bronze Age",
      "printed_page_number": "45",
      "level": 2
    }},
    {{
      "chapter_number": null,
      "title": "Part II: Medieval Period",
      "printed_page_number": "89",
      "level": 1
    }},
    {{
      "chapter_number": 3,
      "title": "Feudal Systems",
      "printed_page_number": "95",
      "level": 2
    }},
    {{
      "chapter_number": null,
      "title": "Bibliography",
      "printed_page_number": "203",
      "level": 1
    }}
  ],
  "toc_page_range": {{"start_page": 5, "end_page": 6}},
  "total_chapters": 4,
  "total_sections": 3,
  "parsing_confidence": 0.95,
  "notes": [
    "Extracted 7 entries (Phase 2 estimated X-Y entries)",
    "Applied Pattern 1: Merged 'Part I' header with 'The Ancient World' subtitle",
    "Applied Pattern 1: Merged 'Part II' header with 'Medieval Period' subtitle",
    "Pattern 2: Standalone entries for Foreword, Bibliography (have page numbers)",
    "Found numbered chapters (1-3) under parts, preserved numbering",
    "Verified all entries have page numbers (no orphaned parents)"
  ]
}}

**FIELD RULES:**
- entries: ALL entries you found after pattern-based merging
- chapter_number: Integer for numbered chapters, null for parts/front matter/back matter
- title: Clean title
  * For merged patterns: Include part label ("Part I: Title")
  * For chapters: Remove number prefix
- printed_page_number: String from OCR (NEVER null after proper merging)
- level: 1/2/3 from visual indentation + semantic hierarchy
- toc_page_range: Scan page numbers provided in user message
- total_chapters: Count of level=1 entries
- total_sections: Count of level=2+ entries
- parsing_confidence: 0.0-1.0 based on self-verification
- notes: Document which patterns you applied, self-verification results
</output_schema>

<output_requirements>
Return ONLY valid JSON.
No markdown code fences.
No explanatory text.
</output_requirements>"""
