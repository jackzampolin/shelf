"""
Prompts for build-structure stage.
"""

STRUCTURE_ANALYSIS_PROMPT = """You are analyzing a scanned book to extract structural metadata from the labels stage output.

You will receive TWO sources of information:
1. **Report Data** (GROUND-UP): Page-by-page analysis from the labels stage
2. **Table of Contents** (TOP-DOWN): The book's declared structure (if available)

**CRITICAL - Page Number Distinction:**
- **SCAN page numbers** = Sequential file numbers (1, 2, 3, ..., N) - used in report data and output
- **PRINTED page numbers** = Numbers printed on actual book pages (may start at 1, use roman numerals, or be missing)
- The report "page_num" column = SCAN page number
- The report "printed_page_number" column = PRINTED page number (if detected)
- ToC references = PRINTED page numbers
- Your output page_range must use SCAN page numbers (from page_num column)

**Report Data** includes the following columns for each page:
- page_num: SCAN page number (sequential 1-N) ← USE THIS FOR OUTPUT
- printed_page_number: PRINTED page number from the book (may be null, roman, or arabic)
- numbering_style: Style of printed page number (roman, arabic, none)
- page_region: Detected region (front_matter, toc_area, body, back_matter)
- total_blocks_classified: Number of content blocks on page
- avg_classification_confidence: Average confidence of block classifications
- has_chapter_heading: Boolean (True/False) - Does this page contain a CHAPTER_HEADING block?
- has_section_heading: Boolean (True/False) - Does this page contain a SECTION_HEADING block?

**CRITICAL - Data Quality Warnings:**
- **has_chapter_heading markers may include false positives** (e.g., standalone page numbers like "17" mistaken for headings)
- **ToC page numbers may be wrong or missing**
- **Neither source is 100% reliable** - use both together and be conservative
- Phase 2 validation will verify your output against actual page text using LLM

**How to Use Both Sources Together:**

1. **Detect Hierarchy Pattern** (books vary!):
   - Look for "Part I", "Part II", "Part III" patterns in ToC or has_chapter_heading pages
   - Look for numbered chapters "1", "2", "3" separate from part markers
   - Common patterns:
     * Parts → Chapters (e.g., Part I contains Chapter 1-5, Part II contains Chapter 6-10)
     * Chapters only (most common - numbered sequentially)
     * Chapters → Sections (chapters contain named subsections)

2. **If book has PARTS (major divisions like "Part I", "Part II"):**
   - Extract Parts as "chapters" in output
   - Parts typically have titles like "Part I: Introduction" or "Part III April-May 1945"
   - Parts start on pages with BOTH has_chapter_heading=True AND heading text containing "Part"
   - Numbered chapter markers (1, 2, 3...) within parts should be mapped to sections[] within that part

3. **If book has CHAPTERS only (no parts):**
   - Extract chapters as "chapters" in output
   - Look for has_chapter_heading=True markers
   - Use ToC to get chapter titles and approximate page numbers
   - Cross-reference: ToC chapter → find nearest has_chapter_heading=True page

4. **Cross-validation Strategy:**
   - ToC entry says "Chapter X ... page N" → find SCAN page where:
     * printed_page_number ≈ N (within ±3 pages)
     * AND has_chapter_heading=True
   - If ToC has no page number, search for has_chapter_heading=True with matching title pattern
   - If multiple has_chapter_heading=True pages exist, prefer the one closest to ToC's printed page
   - **Be conservative**: If unclear which page is correct, choose the ToC's printed page reference

5. **False Positive Detection:**
   - Standalone numbers (like "17") on has_chapter_heading pages may be chapter numbers, NOT part boundaries
   - If a has_chapter_heading page has only a number (no "Part", no title), it's likely a chapter within a part
   - Prefer pages with full headings like "Part IV June-July 1945" over bare numbers

Your Task:
Analyze BOTH sources (when available) to extract the book's structure with high precision.

1. **Front Matter** (pages before main body):
   - Identify: title_page, copyright_page, dedication, epigraph
   - Identify: toc (table of contents), preface, foreword, introduction
   - Note page numbering style (usually roman numerals: i, ii, iii, iv, ...)
   - Front matter typically ends where arabic numerals (1, 2, 3) begin

2. **Chapters** (or Parts if book uses that hierarchy):

   **STEP 1: Determine hierarchy pattern**
   - Count pages with has_chapter_heading=True in report
   - Check if ToC entries contain "Part" keywords
   - Look at the ratio: If book has ~5-10 major divisions, likely Parts
   - If book has 20+ divisions, likely Chapters

   **STEP 2: Extract top-level divisions**
   - If book has Parts: Extract only Part boundaries as "chapters"
     * Use ToC level=1 entries with "Part" in title
     * Match to has_chapter_heading=True pages near ToC's printed_page_number
     * Skip bare numbered pages (like "17") - those are chapters within parts
   - If book has Chapters only: Extract all chapter boundaries
     * Use all has_chapter_heading=True pages with full headings
     * Match with ToC to get chapter titles
     * Number sequentially (1, 2, 3, ...)

   **STEP 3: Validation checks**
   - Chapter count should roughly match ToC level=1 count (±1)
   - Chapter page ranges shouldn't overlap
   - Each chapter should have at least a few pages (not single-page chapters)

3. **Sections** (subsections within chapters/parts):

   **For books with Parts:**
   - Numbered chapters within parts → sections[] array
   - Example: Part III (pages 128-247) contains Chapter 12-17 → add 6 sections
   - Use has_chapter_heading=True pages that aren't part boundaries
   - Get titles from sequential numbering or ToC level=2 entries

   **For books with Chapters only:**
   - ToC level=2 entries → sections[] within chapters
   - Cross-reference with has_section_heading=True markers
   - Sections are optional - many books have chapters without sections

4. **Back Matter** (pages after main body):
   - Identify: epilogue, afterword, appendices
   - Identify: notes (endnotes), bibliography, index
   - Back matter may restart page numbering or continue from body

5. **Page Numbering Transitions**:
   - Note where numbering style changes (roman -> arabic)
   - Note where numbering restarts (often at chapter 1 or back matter)
   - Document any gaps or discontinuities

Key Heuristics:
- **has_chapter_heading=True is a SIGNAL, not truth** - use it but validate against ToC
- **Look for "Part" keywords** to distinguish Parts from Chapters
- **Prefer ToC-matched pages** over isolated has_chapter_heading=True markers
- **Count matters**: 5-10 top divisions? Parts. 20-40 divisions? Chapters.
- **Be conservative**: When uncertain, extract fewer, broader divisions
- has_section_heading=True marks section boundaries within chapters
- Front matter usually has roman numerals (i, ii, iii) or no page numbers
- Main body usually starts at page 1 with arabic numerals
- Region transitions (front_matter -> body -> back_matter) are hints, not rules
- Large gaps in printed page numbers may indicate parts/section changes
- Photo inserts often have no page numbers (legitimate gaps)
- **Standalone page numbers** (like "17") on has_chapter_heading pages are likely chapters-within-parts, not top-level divisions

Output Format:
Return JSON with this EXACT structure:

```json
{
  "front_matter": {
    "title_page": {"start_page": 1, "end_page": 1},
    "copyright_page": {"start_page": 2, "end_page": 2},
    "dedication": {"start_page": 3, "end_page": 3},
    "epigraph": null,
    "toc": {"start_page": 6, "end_page": 7},
    "preface": {"start_page": 9, "end_page": 15},
    "foreword": null,
    "introduction": null,
    "other": [
      {"label": "Timeline", "page_range": {"start_page": 16, "end_page": 16}}
    ],
    "page_numbering_style": "roman"
  },
  "chapters": [
    {
      "chapter_number": 1,
      "title": "Part I: Introduction",
      "page_range": {"start_page": 17, "end_page": 89},
      "sections": [
        {"title": "Chapter 1", "page_range": {"start_page": 17, "end_page": 35}, "level": 1},
        {"title": "Chapter 2", "page_range": {"start_page": 36, "end_page": 60}, "level": 1},
        {"title": "Chapter 3", "page_range": {"start_page": 61, "end_page": 89}, "level": 1}
      ]
    },
    {
      "chapter_number": 2,
      "title": "Part II: The War Years",
      "page_range": {"start_page": 90, "end_page": 200},
      "sections": []
    }
  ],
  "back_matter": {
    "epilogue": null,
    "afterword": null,
    "appendices": null,
    "notes": {"start_page": 371, "end_page": 437},
    "bibliography": null,
    "index": {"start_page": 438, "end_page": 447},
    "other": [
      {"label": "Acknowledgments", "page_range": {"start_page": 448, "end_page": 449}}
    ],
    "page_numbering_style": null
  },
  "total_chapters": 1,
  "total_sections": 0,
  "body_page_range": {"start_page": 17, "end_page": 370},
  "page_numbering_changes": []
}
```

IMPORTANT: Use {"start_page": N, "end_page": M} format for ALL page ranges, not nested objects.

Important:
- **Be conservative**: Extract fewer, broader divisions (Parts) rather than many small ones
- **Hierarchy detection**: Look for "Part" patterns in ToC and has_chapter_heading pages
- **For Part-based books**: Extract Parts as chapters, numbered chapters as sections[]
- **For Chapter-only books**: Extract chapters directly, sections[] may be empty or from ToC level=2
- **Validate against ToC**: Chapter count should roughly match ToC level=1 count
- **False positives**: Ignore standalone numbers like "17" that don't have part/chapter titles
- If uncertain about a boundary, note it in page_numbering_changes
- Empty sections are OK (e.g., no dedication, no epilogue)
- Validate your page ranges don't overlap or skip pages
- **Phase 2 will verify**: Your output will be checked against actual page text, so be accurate
"""

TOC_PARSING_PROMPT = """You are parsing a Table of Contents (ToC) from a scanned book to extract chapter structure.

You will receive the text content from the ToC pages (extracted from the book's front matter).

Your Task:
Parse the ToC to extract all chapter and section entries with their page numbers.

Look for patterns like:
- "Chapter 1: Title ........... 15"
- "I. Title ........... 23"
- "1 Title 45"
- Indented sections under chapters
- Roman numeral chapters (I, II, III) or arabic (1, 2, 3)

**IMPORTANT - Page Number Distinction:**
- The ToC contains PRINTED page numbers (the numbers printed on the actual book pages)
- These are NOT the same as scan/file page numbers (sequential numbering of scanned images)
- Example: ToC says "Chapter 1 ... 1" means printed page "1", which might be scan page 16
- Extract the PRINTED page numbers exactly as they appear in the ToC

Key Instructions:
1. **Extract chapter entries** (level=1):
   - Main chapter entries in ToC
   - Extract chapter number if present (could be numeric, roman, or absent)
   - Extract title text
   - Extract PRINTED page number reference (not scan page number!)

2. **Extract section entries** (level=2 or 3):
   - Look for subsections listed under chapters in the ToC
   - Use indentation, formatting, or font size to determine hierarchy
   - Level 2 = sections directly under a chapter
   - Level 3 = subsections under a level 2 section
   - Associate each section with its parent chapter using chapter_number field
   - If a section doesn't have a clear chapter parent, leave chapter_number as null

3. **Handle various formats**:
   - "Chapter 1: Title ... 15" → chapter_number=1, title="Title", printed_page_number=15
   - "I. Introduction ... 5" → chapter_number=1, title="Introduction", printed_page_number=5
   - "Preface ... ix" → chapter_number=None, title="Preface", printed_page_number=None (roman numeral - convert if possible or set null)
   - Missing page numbers are OK (set to null)

4. **Quality checks**:
   - Skip non-content entries (like "Contents", "List of Figures")
   - Skip blank lines and headers
   - Be conservative: only extract clear entries
   - Note any parsing difficulties

Output Format:
Return JSON with this EXACT structure:

```json
{
  "entries": [
    {
      "chapter_number": 1,
      "title": "The Early Years",
      "printed_page_number": 15,
      "level": 1
    },
    {
      "chapter_number": 1,
      "title": "Childhood",
      "printed_page_number": 17,
      "level": 2
    },
    {
      "chapter_number": 2,
      "title": "The War Years",
      "printed_page_number": 45,
      "level": 1
    }
  ],
  "toc_page_range": {
    "start_page": 6,
    "end_page": 8
  },
  "total_chapters": 2,
  "total_sections": 1,
  "parsing_confidence": 0.95,
  "notes": ["Roman numeral chapters converted to numeric", "Some dotted lines were unclear"]
}
```

Important:
- Extract ALL entries you can identify with reasonable confidence
- Use level to indicate hierarchy (1=chapter, 2=section, 3=subsection)
- Page numbers in output should be PRINTED page numbers from the ToC
- If PRINTED page numbers use roman numerals (i, ii, iii), convert to arabic (1, 2, 3) if possible, otherwise set to null
- Example: "Introduction ... ix" → printed_page_number=9 (if you can convert ix→9) or null
- Set parsing_confidence based on ToC clarity (0.0-1.0)
- Add notes[] for any ambiguities or issues encountered (e.g., "Roman numerals converted", "Page numbers missing")
"""
