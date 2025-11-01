"""
Stage 2: Block-Level Classification (1-image vision call + Stage 1 context)

Focuses on detailed per-block classification using Stage 1 structural insights.
"""

STAGE2_SYSTEM_PROMPT = """<role>
You are a content block classifier. You receive:
1. ONE page image (for visual analysis)
2. OCR blocks (text regions with positions)
3. Stage 1 structural analysis (from 3-image context)

Your job: Classify each OCR block by content type.
</role>

<vision_first_principle>
The page IMAGE shows layout, typography, and visual structure.
OCR TEXT provides the words.

Use both:
- IMAGE → indentation, font size, position, whitespace
- OCR TEXT → content keywords, patterns
</vision_first_principle>

<task>
For each OCR block on this page, assign a classification:

**Structural blocks:**
- PART_HEADING: Major division ("Part IV", "Book Two")
- CHAPTER_HEADING: Chapter start heading
- SECTION_HEADING: Major section within chapter
- SUBSECTION_HEADING: Second-level section
- SUBSUBSECTION_HEADING: Third-level section
- HEADER, FOOTER, PAGE_NUMBER: Running headers/footers

**Content blocks:**
- BODY: Regular paragraph text
- QUOTE: Indented or offset quotation
- EPIGRAPH: Opening quote/motto
- FOOTNOTE: Small text at page bottom with markers

**Front matter blocks:**
- TITLE_PAGE, COPYRIGHT, DEDICATION
- TABLE_OF_CONTENTS, PREFACE, FOREWORD, INTRODUCTION

**Back matter blocks:**
- EPILOGUE, APPENDIX, GLOSSARY, ACKNOWLEDGMENTS
- ENDNOTES, BIBLIOGRAPHY, REFERENCES, INDEX

**Special blocks:**
- CAPTION, ILLUSTRATION_CAPTION, PHOTO_CREDIT
- TABLE, MAP_LABEL, DIAGRAM_LABEL
- OCR_ARTIFACT: Garbled/corrupted text
- OTHER: Unclear classification

Use Stage 1 context to inform decisions (see below).
</task>

<using_stage1_context>
**You receive Stage 1 analysis providing:**

1. **Structural boundary info:**
   - If page is chapter_start → First large block is likely CHAPTER_HEADING
   - If page is part_start → First block is likely PART_HEADING
   - If NOT a boundary → Be cautious labeling CHAPTER_HEADING

2. **Page region:**
   - front_matter → Expect PREFACE, INTRODUCTION, TABLE_OF_CONTENTS
   - body → Expect BODY, CHAPTER_HEADING, SECTION_HEADING
   - back_matter → Expect INDEX, BIBLIOGRAPHY, ENDNOTES

**Use this context as strong guidance, not absolute rules.**
Stage 1 observations help you understand the page's role in the book's structure.
</using_stage1_context>

<classification_guidelines>
**Hierarchy detection (from visual cues):**

PART_HEADING:
- Very large, prominent text (2x+ body size)
- "Part", "Book", "Volume" keywords
- Lots of whitespace (70%+ page empty)
- Stage 1 confirms: is_boundary=true, boundary_type="part_start"

CHAPTER_HEADING:
- Large text (1.5x+ body size)
- Often centered or at top of page
- Stage 1 confirms: is_boundary=true, boundary_type="chapter_start"
- May include chapter number ("1", "Chapter 5", "XVII")

SECTION_HEADING:
- Larger than body (1.2-1.5x) but smaller than chapter
- May be bold or different font
- Appears within chapter content

SUBSECTION_HEADING / SUBSUBSECTION_HEADING:
- Slightly larger or bold
- Nesting indicated by indentation or numbering (1.2.3 style)

**Position-based:**

HEADER / FOOTER:
- Top 10% or bottom 15% of page
- Small text (0.8-1.0x body size)
- Running title or chapter name

PAGE_NUMBER:
- Very small, in margin/corner
- Just a number, minimal styling
- Note: Stage 1 extracted printed page number separately

FOOTNOTE:
- Bottom 20% of page
- Smaller font (0.7-0.9x body size)
- Often has marker (*, †, 1)

**Content-based:**

QUOTE:
- Indented from both margins (visible in OCR position data)
- May have attribution line

TABLE_OF_CONTENTS:
- Stage 1 confirms: is_toc_page=true
- Multi-column layout (dots connecting to numbers)
- List of titles with page numbers

BIBLIOGRAPHY / INDEX:
- Hanging indent pattern
- Alphabetical ordering
- Stage 1 confirms: page_region="back_matter"

BODY:
- Default for normal paragraph text
- Regular font, left-aligned
- Most common block type

OCR_ARTIFACT:
- Garbled characters (|@#$, random symbols)
- Partial words or fragments
- Visual inspection shows no corresponding text
</classification_guidelines>

<self_verification>
**Before returning, verify:**

1. **Block count match:**
   - How many OCR blocks provided? ___
   - How many classifications did I return? ___
   - Must be EXACTLY equal (no skipping, no adding)

2. **Hierarchy coherence:**
   - If I classified CHAPTER_HEADING, does Stage 1 confirm is_boundary=true?
   - If I classified multiple CHAPTER_HEADING, is that realistic? (usually one per page)

3. **Region consistency:**
   - Stage 1 says page_region="front_matter"
   - Did I classify blocks as BODY, CHAPTER_HEADING? (unlikely in front matter)
   - If mismatch: Re-examine image and Stage 1 context

4. **Confidence calibration:**
   - 0.95-1.0: Image + OCR + Stage 1 all agree
   - 0.85-0.94: Strong signals but minor ambiguity
   - 0.70-0.84: Educated guess based on limited signals

**If any check fails → Fix before returning!**
</self_verification>"""


def build_stage2_user_prompt(
    ocr_blocks_summary: str,
    ocr_text: str,
    stage1_results: dict,
    current_page: int,
    total_pages: int,
) -> str:
    """Build user prompt for Stage 2 with Stage 1 context."""

    # Extract key Stage 1 insights
    is_boundary = stage1_results.get('structural_boundary', {}).get('is_boundary', False)
    boundary_type = stage1_results.get('structural_boundary', {}).get('boundary_type')
    page_region = stage1_results.get('page_region', {}).get('region', 'body')

    boundary_context = ""
    if is_boundary and boundary_type:
        boundary_context = f"\n⚠️  Stage 1 detected: This is a **{boundary_type}** page"

    return f"""<page_context>
Page {current_page} of {total_pages}

**Stage 1 Analysis:**
- Page region: **{page_region}**{boundary_context}
</page_context>

<ocr_blocks>
{ocr_blocks_summary}
</ocr_blocks>

<ocr_text>
{ocr_text}
</ocr_text>

<instructions>
Classify each OCR block using:
1. The page IMAGE (for layout, typography, position)
2. OCR text (for content)
3. Stage 1 context (for structural guidance)

Return exactly {ocr_blocks_summary.count('Block')} classifications (one per OCR block).

Use Stage 1 context to guide your decisions:
- Boundary pages → Expect headings
- Region={page_region} → Expect appropriate content types
</instructions>

Classify and return JSON with block classifications."""
