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
- IMAGES → indentation, hierarchy, entry count, visual layout
- OCR TEXT → exact titles, chapter numbers, page numbers

**Title cleanup rules:**
For numbering style "{numbering_style}":
- "I. Title" → chapter_number=1, title="Title"
- "Chapter 5: Title" → chapter_number=5, title="Title"
- "1. Title" → chapter_number=1, title="Title"
- Title field must NEVER include the chapter number

**Hierarchy detection (from images):**
- Level 1: Flush left (top-level chapters/parts)
- Level 2: Indented once (sections)
- Level 3: Indented twice (subsections)

**Page numbers (from OCR):**
- Roman numerals: "ix", "xiv" (strings, not integers)
- Arabic numerals: "15", "203" (strings, not integers)
- Missing: null
</extraction_instructions>

<self_verification>
**CRITICAL: After extraction, verify BEFORE returning:**

1. **Count check:**
   - Phase 2 observed {approx_count}
   - How many did I extract? ___
   - If significantly different (off by 3+), LOOK AGAIN at images

2. **Sequence check (if numbered):**
   - List my chapter numbers: [1, 2, 3, ...]
   - Are there gaps? (e.g., [1, 2, 4, 5] is missing 3)
   - If gaps exist, LOOK AGAIN at images/OCR to find missing entries

3. **Title cleanup check:**
   - Do any titles still have number prefixes? ("I.", "1.", "Chapter")
   - If yes, remove them now

4. **Page number check:**
   - Are page numbers strings (not integers)?
   - Did I extract them from OCR text accurately?

5. **Boundary check:**
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
      "chapter_number": 1,
      "title": "The Early Years",
      "printed_page_number": "15",
      "level": 1
    }},
    {{
      "chapter_number": 1,
      "title": "Childhood",
      "printed_page_number": "17",
      "level": 2
    }}
  ],
  "toc_page_range": {{"start_page": 5, "end_page": 6}},
  "total_chapters": 15,
  "total_sections": 8,
  "parsing_confidence": 0.95,
  "notes": [
    "Extracted X entries (Phase 2 estimated {approx_count})",
    "Verified no gaps in chapter sequence",
    "Cleaned Roman numeral prefixes from titles"
  ]
}}

**RULES:**
- entries: ALL entries you found (may differ from Phase 2 estimate)
- chapter_number: Integer or null (extract from OCR, then remove from title)
- title: Clean title WITHOUT number prefix
- printed_page_number: String from OCR or null
- level: 1/2/3 from VISUAL indentation
- toc_page_range: Scan page numbers provided in user message
- total_chapters: Count of level=1 entries
- total_sections: Count of level=2+ entries
- parsing_confidence: 0.0-1.0 based on your self-verification
- notes: Document your self-verification results
</output_schema>

<output_requirements>
Return ONLY valid JSON.
No markdown code fences.
No explanatory text.
</output_requirements>"""
