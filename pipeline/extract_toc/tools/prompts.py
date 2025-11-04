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
  {{"chapter_number": null, "title": "Part I", "printed_page_number": null, "level": 1}},
  {{"chapter_number": null, "title": "April 12, 1945", "printed_page_number": "1", "level": 2}},
  {{"chapter_number": null, "title": "The First Days", "printed_page_number": "15", "level": 2}},
  {{"chapter_number": null, "title": "Part II", "printed_page_number": null, "level": 1}},
  {{"chapter_number": null, "title": "The Political Education", "printed_page_number": "39", "level": 2}}
]
```

**CRITICAL:** Keep parent headers as SEPARATE entries with null page numbers. They provide structure.

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
  {{"chapter_number": null, "title": "Part I", "printed_page_number": null, "level": 1}},
  {{"chapter_number": 1, "title": "April 12, 1945", "printed_page_number": "1", "level": 2}},
  {{"chapter_number": 2, "title": "The First Days", "printed_page_number": "15", "level": 2}},
  {{"chapter_number": null, "title": "Part II", "printed_page_number": null, "level": 1}},
  {{"chapter_number": 3, "title": "The Political Education", "printed_page_number": "39", "level": 2}}
]
```

**CRITICAL:** Keep Parts separate with null page numbers. Chapter numbers go in chapter_number field.

**HOW TO DISTINGUISH PATTERNS:**

Key signal: **PAGE NUMBERS indicate complete entries**

1. Line WITH page number = likely complete entry (Pattern 2, 3, or child in Pattern 1/4)
2. Line WITHOUT page number = either:
   - Parent (if followed by indented entries WITH page numbers) → Pattern 1 or 4
   - Title continuation (if next line completes the thought) → Pattern 3
   - Standalone rare case (decorative headers, skip these)

3. Use visual context from images:
   - If "Part I" followed by indented entries → Pattern 1 or 4 (keep Part separate)
   - If incomplete sentence followed by continuation → Pattern 3 (merge lines)
   - If standalone entry with page number → Pattern 2 (keep as-is)
</pattern_recognition>

<numbering_extraction>
For numbering style "{numbering_style}":

**Chapter numbering (goes in chapter_number field):**
- "1. Title" → chapter_number=1, title="Title"
- "Chapter 5: Title" → chapter_number=5, title="Title"
- "I. Title" (if Roman = chapters) → chapter_number=1, title="Title"

**Part numbering (separate entries, goes in title field):**
- "Part I" (no page number) → separate entry: title="Part I", chapter_number=null, printed_page_number=null
- "I" (if Roman = parts) → title="Part I" (spell out), chapter_number=null, printed_page_number=null

**How to tell Part vs Chapter Roman numerals:**
- Context: If followed by indented numbered items (1, 2, 3), it's a Part
- Context: If standalone with page number, it's a Chapter
- Visual: Parts usually larger/bolder, flush left
- Semantic: "Part I" is explicit, lone "I" requires context

**Title cleanup:**
- NEVER put Part numbers in chapter_number field
- ALWAYS remove chapter prefixes from title ("Chapter 5: Title" → "Title")
- Keep Parts as SEPARATE entries (don't merge with following chapters)

**Page numbers (from OCR):**
- Roman numerals: "ix", "xiv" (strings, not integers)
- Arabic numerals: "15", "203" (strings, not integers)
- Missing: null (for structural parent entries like Parts)
</numbering_extraction>

<hierarchy_detection>
**Level assignment based on visual indentation in images:**

- Level 1: Flush left entries
  - Parts, main chapters, front/back matter
  - No indentation visible

- Level 2: First level of indentation
  - Sections/sub-chapters under Parts
  - Clearly indented from left margin

- Level 3: Second level of indentation
  - Subsections under sections
  - Indented further than level 2


<self_verification>
**CRITICAL: After extraction, verify BEFORE returning:**

1. **Pattern application check:**
   - Did I find multi-line titles (Pattern 3)?
   - If yes, did I merge continuation lines into single entries?
   - Did I keep structural parents (Parts, Sections) as separate entries?
   - RULE: Entries have page numbers UNLESS they are structural parents (Parts/Sections)

2. **Part/Chapter distinction check:**
   - Do I have entries like: chapter_number=1, title="Part I"?
   - This is WRONG! Part numbers go in title field, chapter_number should be null
   - CORRECT for Parts: chapter_number=null, title="Part I", printed_page_number=null
   - CORRECT for Chapters: chapter_number=1, title="Chapter Title", printed_page_number="10"

3. **Count check:**
   - Phase 2 observed {approx_count}
   - How many did I extract? ___
   - If significantly different (off by 5+), LOOK AGAIN at images to verify
   - Check if I missed entries or incorrectly merged multi-line titles

4. **Sequence check (if numbered chapters):**
   - List my chapter numbers: [1, 2, 3, ...]
   - Are there gaps? (e.g., [1, 2, 4, 5] is missing 3)
   - If gaps exist, LOOK AGAIN at images/OCR to find missing entries

5. **Title cleanup check:**
   - Do any chapter titles still have number prefixes? ("1.", "Chapter 5:")
   - If yes, remove them (they should be in chapter_number field)
   - Are Part titles clean? (e.g., "Part I", "Part II")
   - If Part has subtitle on same line, include it (e.g., "Part I: Introduction")

6. **Page number check:**
   - Are ALL page numbers strings (not integers)?
   - Did I extract them from OCR text accurately?
   - Do structural parents (Parts/Sections) correctly have null page numbers?
   - Do content entries (Chapters) have page numbers?

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
      "title": "Part I",
      "printed_page_number": null,
      "level": 1
    }},
    {{
      "chapter_number": 1,
      "title": "Early Civilizations",
      "printed_page_number": "3",
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
      "title": "Part II",
      "printed_page_number": null,
      "level": 1
    }},
    {{
      "chapter_number": 3,
      "title": "Feudal Systems",
      "printed_page_number": "89",
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
  "total_chapters": 5,
  "total_sections": 3,
  "parsing_confidence": 0.95,
  "notes": [
    "Extracted 9 entries (Phase 2 estimated X-Y entries)",
    "Pattern 1: Kept Parts (I, II) as separate structural entries with null page numbers",
    "Pattern 2: Standalone entries for Foreword, Bibliography, and numbered chapters",
    "Found 3 numbered chapters (1-3) under parts, preserved numbering",
    "Verified structural parents have null page numbers, content entries have page numbers"
  ]
}}

**FIELD RULES:**
- entries: ALL entries you found (Parts kept separate from chapters)
- chapter_number: Integer for numbered chapters, null for parts/front matter/back matter
- title: Clean title
  * For Parts: "Part I", "Part II" (keep simple unless subtitle on same line)
  * For chapters: Remove number prefix ("Chapter 5: Title" → "Title")
- printed_page_number: String from OCR, null for structural parents (Parts/Sections)
- level: 1/2/3 from visual indentation in images
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
