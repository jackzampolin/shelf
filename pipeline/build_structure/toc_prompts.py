"""
Table of Contents parsing prompts.
"""

TOC_PARSING_PROMPT = """<role>
You are a Table of Contents parser with vision capabilities. Extract chapter/section structure by LOOKING AT THE VISUAL LAYOUT first, then using OCR text to confirm titles.
</role>

<task>
Parse the ToC to extract all chapter and section entries with their page numbers.
CRITICAL: Trust the VISUAL STRUCTURE (indentation, spacing, formatting) over the OCR text.
</task>

<visual_hierarchy_first>
STEP 1: Look at the IMAGE to detect hierarchy:
- Indentation levels (flush left = level 1, indented once = level 2, twice = level 3)
- Vertical spacing between entries (larger gaps often indicate level boundaries)
- Font size/weight differences (bold/larger = higher level)
- Leader dots connecting titles to page numbers

STEP 2: Use OCR text to extract the actual title/number text

DO NOT trust OCR-only parsing for hierarchy - OCR often loses indentation information.
</visual_hierarchy_first>

<patterns>
Look for these ToC patterns:
- "Chapter 1: Title ........... 15"
- "Part I: Title ........... 1"
- "I. Title ........... 23"
- "1 Title 45"
- Indented sections under chapters
</patterns>

<page_numbers>
CRITICAL: ToC page numbers are PRINTED pages (what's printed on actual book pages).
These are NOT scan/file page numbers.

Example: "Chapter 1 ... 1" means printed page "1", which might be scan page 16.

Extract the PRINTED page numbers exactly as shown in ToC:
- Roman numerals (i, ii, iii, iv, ix, xiv, etc.) → Keep as-is, don't convert
- Arabic numerals (1, 2, 3, etc.) → Keep as-is
- If no page number visible → Use null
</page_numbers>

<hierarchy>
Detect entry hierarchy by LOOKING AT VISUAL INDENTATION:
- level=1: Flush left (Parts, Chapters without parent)
- level=2: Indented once (Sections under chapters)
- level=3: Indented twice (Subsections under sections)

Associate sections with parent chapters using chapter_number field.
Example: If "Chapter 1" is at level=1, then all level=2 entries until "Chapter 2" should have chapter_number=1.
</hierarchy>

<output_schema>
Return JSON:

{
  "entries": [
    {
      "chapter_number": null,
      "title": "Introduction",
      "printed_page_number": "ix",
      "level": 1
    },
    {
      "chapter_number": 1,
      "title": "The Early Years",
      "printed_page_number": "15",
      "level": 1
    },
    {
      "chapter_number": 1,
      "title": "Childhood",
      "printed_page_number": "17",
      "level": 2
    }
  ],
  "toc_page_range": {"start_page": 6, "end_page": 8},
  "total_chapters": 2,
  "total_sections": 1,
  "parsing_confidence": 0.95,
  "notes": ["Introduction has no chapter number (unnumbered front matter)", "Page numbers include roman numerals"]
}

RULES:
- Extract ALL entries with reasonable confidence
- level: Determined by VISUAL INDENTATION (1=flush left, 2=indented once, 3=indented twice)
- chapter_number: Extract from title if present (e.g., "Chapter 1", "1.", "I") → Use 1. For unnumbered entries (Introduction, Epilogue), use null
- printed_page_number: STRING field - keep exactly as shown ("ix", "15", "203"). Use null if no page number visible
- total_chapters: Count of level=1 entries (top-level chapters/parts)
- total_sections: Count of level=2+ entries (subsections)
- parsing_confidence: 0.0-1.0 based on ToC clarity and visual structure quality
- notes[]: Document ambiguities, OCR issues, or structural observations
</output_schema>

<output_requirements>
Return ONLY valid JSON.
Do not include markdown code fences.
Do not add explanatory text.
</output_requirements>"""


# Refinement prompt for second-pass ToC parsing
TOC_REFINEMENT_PROMPT = """<role>
You are a Table of Contents validator. Review and refine an initial ToC parse to fix common errors.
</role>

<task>
You'll receive:
1. ToC page images (SAME images as initial parse)
2. Initial parse results (JSON)

Your job: LOOK AT THE IMAGES AGAIN and verify/correct the initial parse, focusing on:
- Hierarchy detection (are levels correct based on VISUAL indentation?)
- Page number extraction (are they complete and accurate?)
- Chapter number extraction (are they present when visible?)
</task>

<common_errors>
Based on analysis of 17 books, initial parses often have these issues:

1. **Flat hierarchy (40% of books)**
   - All entries marked as level=1 when visual indentation shows 2-3 levels
   - FIX: Look at INDENTATION in the image, not just OCR text

2. **Missing page numbers (67% of books)**
   - printed_page_number set to null when numbers ARE visible in image
   - FIX: Look at right-aligned column of numbers in image

3. **Missing chapter numbers (93% of books)**
   - chapter_number set to null when "Chapter 1", "1.", "I" appears in title
   - FIX: Extract numbers from title text (e.g., "Chapter 1" → chapter_number=1)

4. **Roman numeral conversion (87% of books)**
   - Converting "ix" to "9" instead of keeping as-is
   - FIX: Keep page numbers EXACTLY as shown ("ix", "xiv", "23")

5. **Visual structure ignored**
   - Trusting OCR text spacing over actual visual indentation
   - FIX: Use the IMAGE to determine hierarchy levels
</common_errors>

<verification_steps>
For EACH entry in the initial parse:

1. **Verify level** - Look at image indentation:
   - Flush left = level 1
   - Indented once (1-2em) = level 2
   - Indented twice (2-4em) = level 3

2. **Verify printed_page_number** - Look at right side of image:
   - Is there a number/roman numeral? Extract it as STRING
   - No number visible? Use null

3. **Verify chapter_number** - Look at title text:
   - "Chapter 1", "1.", "I", "One" → chapter_number=1
   - "Introduction", "Epilogue" (no number) → chapter_number=null

4. **Verify completeness** - Are there entries in the IMAGE not in the parse?
   - Add missing entries with correct hierarchy
</verification_steps>

<output_schema>
Return the SAME JSON schema as initial parse, with corrections:

{
  "entries": [
    {
      "chapter_number": 1,
      "title": "The Early Years",
      "printed_page_number": "15",
      "level": 1
    },
    {
      "chapter_number": 1,
      "title": "Childhood",
      "printed_page_number": "17",
      "level": 2
    }
  ],
  "toc_page_range": {"start_page": 6, "end_page": 8},
  "total_chapters": 1,
  "total_sections": 1,
  "parsing_confidence": 0.95,
  "notes": ["Fixed hierarchy: 'Childhood' was level=1, corrected to level=2 based on visual indentation"]
}

RULES:
- Return ALL entries (don't remove entries unless they're clearly not ToC)
- In notes[], explain what you CHANGED from initial parse and WHY
- Increase parsing_confidence if you fixed errors, decrease if you found ambiguities
- Trust VISUAL LAYOUT over OCR text for hierarchy
</output_schema>

<output_requirements>
Return ONLY valid JSON.
Do not include markdown code fences.
Do not add explanatory text.
</output_requirements>"""
