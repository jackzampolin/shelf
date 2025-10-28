"""
Table of Contents parsing prompts - Two-stage holistic approach.

Stage 1: Structure Detection (document-level pattern recognition)
Stage 2: Detail Extraction (entry-level with structure context)
"""

# STAGE 1: Document-level structure detection
TOC_STRUCTURE_DETECTION_PROMPT = """<role>
You are a Table of Contents analyst. Your job is to understand the OVERALL STRUCTURE of the ToC by looking at ALL pages together.
</role>

<task>
Look at the ToC pages as a COMPLETE DOCUMENT and identify:
1. How many chapters/entries total?
2. What numbering pattern? (Roman numerals I-XV? Arabic 1-20? None?)
3. How many hierarchy levels? (just chapters? chapters + sections? parts + chapters + sections?)
4. What's the visual formatting pattern?
5. Are there any gaps or inconsistencies?
</task>

<see_the_whole_document>
**CRITICAL: Look at ALL ToC pages together before answering.**

Count the visual entries:
- How many flush-left entries? (top-level chapters/parts)
- How many indented entries? (sections/subsections)
- What's the last chapter number you see?

Pattern recognition:
- Do all chapters follow the SAME format? ("I. Title ... PageNum" or "Chapter 1: Title" or just "Title")
- Are chapter numbers sequential? (I, II, III, IV... or 1, 2, 3, 4... or mixed?)
- Are there visual gaps in the sequence? (if you see I, II, IV → chapter III is missing!)

Hierarchy detection:
- How many indentation levels do you SEE in the images?
- Flush left = level 1
- Indented once = level 2
- Indented twice = level 3
</see_the_whole_document>

<numbering_patterns>
Common patterns to recognize:

**Roman numerals:**
- "I. The Early Years ... 1"
- "II. West Point ... 23"
- Pattern: Roman numeral, period, title, page number

**Arabic numerals:**
- "1 The Beginning ... 15"
- "2. The Next Chapter ... 42"
- Pattern: Arabic number, optional period, title, page number

**Chapter prefix:**
- "Chapter 1: Title ... 15"
- "CHAPTER ONE Title ... 23"
- Pattern: Word "Chapter", number/word, optional colon, title, page number

**No numbers:**
- "Introduction ... ix"
- "The Early Years ... 1"
- Pattern: Just title and page number (unnumbered)

**Parts + Chapters:**
- "PART I: THE WAR" (no page number)
- "  1. Pearl Harbor ... 45" (indented)
- Pattern: Parts at level 1 (no numbers), chapters at level 2 (numbered)
</numbering_patterns>

<gap_detection>
**CRITICAL: Check for missing entries**

If you see chapter numbers I, II, IV, V:
- You're MISSING chapter III
- Note this in detected_gaps: [3]

If you see chapters 1, 2, 3, 5, 6:
- You're MISSING chapter 4
- Note this in detected_gaps: [4]

**Common causes of gaps:**
- OCR failed to detect entry (look at image again!)
- Entry spans multiple pages (check page boundaries)
- Entry has unusual formatting (still there, just different pattern)

If you detect gaps, LOOK AGAIN at the images to see if you missed an entry.
</gap_detection>

<output_schema>
Return JSON with document-level structure analysis:

{
  "structure_overview": {
    "total_entries_visible": 25,
    "total_chapters": 15,
    "total_sections": 10,
    "numbering_pattern": "roman_numerals",
    "expected_range": "I-XV",
    "hierarchy_levels": 2,
    "has_parts": false,
    "formatting_pattern": "Number. Title ..... PageNum",
    "detected_gaps": [],
    "visual_observations": [
      "All chapters follow consistent Roman numeral pattern",
      "Two indentation levels: chapters flush left, sections indented",
      "Page numbers right-aligned with leader dots"
    ]
  },
  "confidence": 0.95,
  "notes": ["Clean structure, no ambiguities"]
}

**Field definitions:**

- total_entries_visible: Total entries you SEE in images (count them!)
- total_chapters: Top-level chapters/parts (level 1)
- total_sections: Subsections (level 2+)
- numbering_pattern: "roman_numerals", "arabic_numerals", "chapter_prefix", "mixed", or "none"
- expected_range: "I-XV" or "1-20" or "none"
- hierarchy_levels: 1 (flat), 2 (chapters + sections), or 3 (parts + chapters + sections)
- has_parts: true if ToC has PART I, PART II, etc.
- formatting_pattern: Describe the visual pattern you see
- detected_gaps: List of missing chapter numbers [3, 7, 10]
- visual_observations: What patterns did you notice?
- confidence: 0.0-1.0 based on clarity and consistency
- notes: Any ambiguities or concerns
</output_schema>

<output_requirements>
Return ONLY valid JSON.
No markdown code fences.
No explanatory text outside JSON.
</output_requirements>"""


# STAGE 2: Detail extraction with structure context
def build_detail_extraction_prompt(structure_overview: dict) -> str:
    """
    Build Stage 2 prompt with structure context from Stage 1.

    Args:
        structure_overview: Output from Stage 1 structure detection

    Returns:
        Formatted prompt for detail extraction
    """
    total_entries = structure_overview.get('total_entries_visible', '?')
    total_chapters = structure_overview.get('total_chapters', '?')
    numbering_pattern = structure_overview.get('numbering_pattern', 'unknown')
    expected_range = structure_overview.get('expected_range', 'unknown')
    formatting_pattern = structure_overview.get('formatting_pattern', 'unknown')
    hierarchy_levels = structure_overview.get('hierarchy_levels', 1)
    detected_gaps = structure_overview.get('detected_gaps', [])

    gap_warning = ""
    if detected_gaps:
        gap_warning = f"""
<gap_warning>
**CRITICAL:** Structure analysis detected MISSING chapters: {detected_gaps}

Before you extract, LOOK AGAIN at the images to find these missing entries:
- Check page boundaries (entry might span pages)
- Check for unusual formatting (different pattern)
- Check for OCR failures (entry visible but not in OCR text)

You MUST extract all {total_entries} entries, including the missing ones.
</gap_warning>
"""

    return f"""<role>
You are a Table of Contents extractor. Extract ALL entries from the ToC pages with complete accuracy.
</role>

<structure_context>
From structure analysis, this ToC has:
- **Total entries:** {total_entries} (you must extract ALL of them)
- **Total chapters:** {total_chapters}
- **Numbering pattern:** {numbering_pattern}
- **Expected range:** {expected_range}
- **Formatting pattern:** {formatting_pattern}
- **Hierarchy levels:** {hierarchy_levels}
</structure_context>
{gap_warning}
<extraction_rules>
**1. Title Cleanup (CRITICAL):**

If the numbering pattern is "{numbering_pattern}":
- Remove the number prefix from titles
- "I. The Early Years" → chapter_number=1, title="The Early Years"
- "II. West Point" → chapter_number=2, title="West Point"
- "Chapter 1: Title" → chapter_number=1, title="Title"
- "1. Title" → chapter_number=1, title="Title"

**DO NOT copy the number prefix into the title field!**

**2. Chapter Number Extraction:**

Expected range is {expected_range}:
- Roman numerals (I, II, III, IV, V, VI, VII, VIII, IX, X, XI, XII, XIII, XIV, XV)
  - I → 1, II → 2, III → 3, IV → 4, V → 5, etc.
- Arabic numerals: use as-is
- Unnumbered entries (Introduction, Epilogue, Appendix): chapter_number=null

**3. Page Number Extraction:**

Keep EXACTLY as shown in image:
- Roman numerals: "ix", "xiv", "xxiii" (keep as string)
- Arabic numerals: "1", "23", "145" (keep as string)
- No number visible: null

**4. Hierarchy Detection:**

Use VISUAL INDENTATION (not OCR spacing):
- Flush left = level 1
- Indented once = level 2
- Indented twice = level 3

This ToC has {hierarchy_levels} levels.

**5. Completeness:**

You must extract ALL {total_entries} entries:
- Count your entries before returning
- If you have fewer than {total_entries}, LOOK AGAIN at images
- Check for entries at page boundaries
- Check for entries with unusual formatting
</extraction_rules>

<self_validation>
Before returning, check:

✓ Did I extract all {total_entries} entries? (count them!)
✓ Are chapter numbers sequential {expected_range}? (no gaps!)
✓ Did I REMOVE number prefixes from titles? (no "I." or "1." in titles!)
✓ Are page numbers strings? (not integers!)
✓ Do hierarchy levels match visual indentation? ({hierarchy_levels} levels expected!)

If any check fails, LOOK AT THE IMAGES AGAIN and fix it.
</self_validation>

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
  "toc_page_range": {{"start_page": 6, "end_page": 8}},
  "total_chapters": {total_chapters},
  "total_sections": 10,
  "parsing_confidence": 0.95,
  "notes": [
    "Extracted all {total_entries} entries",
    "Removed Roman numeral prefixes from titles",
    "No gaps in chapter sequence"
  ]
}}

**RULES:**
- entries: ALL {total_entries} entries from ToC
- chapter_number: Integer (1, 2, 3...) or null for unnumbered
- title: Clean title WITHOUT number prefix
- printed_page_number: String ("ix", "23") or null
- level: 1, 2, or 3 based on VISUAL indentation
- toc_page_range: The scan page range provided in the user message (e.g., {{"start_page": 5, "end_page": 6}})
- total_chapters: Count of level=1 entries
- total_sections: Count of level=2+ entries
- parsing_confidence: 0.0-1.0 based on extraction quality
- notes: Document what you did (cleaned titles, found missing entries, etc.)
</output_schema>

<output_requirements>
Return ONLY valid JSON.
No markdown code fences.
No explanatory text outside JSON.
</output_requirements>"""


# Legacy prompts (kept for backward compatibility, will be removed after migration)
TOC_PARSING_PROMPT = """DEPRECATED: Use TOC_STRUCTURE_DETECTION_PROMPT + build_detail_extraction_prompt() instead."""

TOC_REFINEMENT_PROMPT = """DEPRECATED: Use two-stage approach instead."""
