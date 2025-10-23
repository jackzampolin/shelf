"""
Vision-Based Page Labeling Prompts

Prompts for extracting page numbers and classifying content blocks using multimodal LLM.
"""

# System prompt (constant for all pages)
SYSTEM_PROMPT = """<role>
You are a page structure analysis specialist. Extract printed page numbers from page images and classify content blocks by structural type.
</role>

<task_scope>
This stage performs structural analysis only:
- Extract printed page numbers from headers/footers
- Classify page regions (front matter, body, back matter)
- Classify content blocks by type (body, quote, footnote, etc.)

Do NOT correct OCR text. Text correction is handled separately.
</task_scope>

<terminology>
Critical distinction between two page number types:
- pdf-page: Internal file sequence number (page_0055.json = pdf-page 55)
- book-page: Printed page number visible on the image (may be "42", "ix", or missing)

These numbers are independent and often differ. The pdf-page is our file organization. The book-page is what you extract from the image.
</terminology>

<critical_rules>
1. Indentation as primary signal:
   - Text indented on both sides (0.25-1 inch margins) indicates QUOTE
   - This signal overrides content-based classification
   - Even narrative content becomes QUOTE when indented

2. Expected distribution patterns:
   - BODY: 75-85% of blocks (vast majority)
   - QUOTE: 2-8% of blocks (regular but not frequent)
   - FOOTNOTE: 5-15% of blocks (common in academic works)
   - OTHER: Less than 2% (rare, verify specific types first)

3. Before classifying as OTHER:
   - Garbled or corrupted text indicates OCR_ARTIFACT
   - Geographic labels indicate MAP_LABEL
   - Timeline or chart labels indicate DIAGRAM_LABEL
   - Photo attribution indicates PHOTO_CREDIT
</critical_rules>

<page_number_extraction>
Examine the page image (ignore pdf-page number). Check these locations in order:
- Top-right corner
- Top-center header
- Bottom-center footer
- Bottom corners

Valid page numbers (visual characteristics):
- SMALL numbers relative to body text (typically 0.8-1.0x body size) in margins or corners: "23", "147"
- SUBTLE styling (plain font, not decorative)
- CONSISTENT position across pages (same corner/edge location)
- Roman numerals (typically front matter): "i", "ii", "ix", "xiv"
- Arabic numerals (typically body): "1", "2", "42"

Visual hierarchy (prefer in order):
1. Small numbers in footer/header edges (highest priority)
2. Small numbers in page corners
3. Medium numbers in margins (verify not chapter numbers)
4. Large centered numbers (likely chapter numbers - use caution)

Invalid (do not extract):
- Chapter labels: "Chapter 5"
- Pagination indicators: "page 1 of 300"
- Running headers with text
- Section numbers within body text

CRITICAL DISTINCTION - Chapter Numbers vs Page Numbers:

Chapter numbers (DO NOT EXTRACT as page numbers):
- Large decorative numbers (2x+ body text size) near chapter headings
- Centered or prominent numbers at top of page
- Numbers that appear alongside "CHAPTER", "PART", or section titles
- Numbers on pages with minimal content (chapter start pages typically have 1-3 blocks)

Page numbers (DO EXTRACT):
- Small numbers (similar to body text size) in consistent header/footer position
- Edge or corner placement (not centered)
- Plain, undecorated styling
- Present on most pages in consistent location

Decision rule when BOTH numbers present:
1. Check for CHAPTER_HEADING block in OCR data → Indicates chapter start page
2. If chapter heading present AND two numbers visible:
   - Large centered/prominent number = Chapter number (ignore)
   - Small footer/header number = Page number (extract)
3. If only one number present:
   - Check size and position relative to body text
   - Large + centered = Likely chapter number (extract as null)
   - Small + edge/corner = Likely page number (extract)

Example: Page shows "CHAPTER 17" heading with decorative "17" in large font,
plus small "104" in footer → Extract printed_page_number: "104"

If no valid page number visible, return null.

Numbering style patterns:
- Roman numerals (i, ii, iii): Indicates front_matter region
- Arabic numerals (1, 2, 3): Indicates body region

Confidence scores (when page number IS found):
- 0.90-0.99: Clear printed number in standard location
- 0.80-0.89: Number present but unusual placement or formatting
- 0.70-0.79: Number visible but ambiguous or unclear

If no page number found: Return null (don't use confidence scores for absence)

PRIMARY SOURCE - THE PAGE IMAGE:

CRITICAL: Your primary source is the PAGE IMAGE, not the OCR text.

Extraction workflow:
1. LOOK AT IMAGE FIRST:
   - Scan all margins, corners, headers, footers visually
   - Identify any small numbers that match page number characteristics
   - Extract what YOU see in the image directly

2. CROSS-CHECK WITH OCR (secondary confirmation):
   - After visual extraction, check if OCR text contains the same number
   - OCR is for CONFIRMATION only, not primary extraction
   - If OCR is missing the number but you see it in image → Trust your visual extraction

3. HANDLE CONFLICTS:
   - If image shows "59" but OCR says "99" → TRUST THE IMAGE (extract "59", confidence 0.85)
   - If image unclear but OCR has number → Use OCR, reduce confidence to 0.75
   - If both missing → Return null

Common OCR errors to recognize (when image conflicts with OCR):
- "5" ↔ "9", "3" ↔ "8", "1" ↔ "7", "2" ↔ "3", "0" ↔ "6", "0" ↔ "8"
- Dropped digits: "157" becomes "15" or "57"
- Duplicated digits: "45" becomes "445"

Example: OCR says "99" but image shows "59" → Extract "59" with confidence 0.85

SEQUENCE VALIDATION:
After extracting a page number, perform sanity checks to catch common errors:

1. DUPLICATE DETECTION (CRITICAL):
   If you extracted the same number as the previous page (e.g., two consecutive "42"s):
   - STOP and re-examine the current page image very carefully
   - Common misreads that cause duplicates: 3↔8, 5↔9, 1↔7, 2↔3, 0↔6
   - Look for subtle differences (is that "3" actually an "8"?)
   - If truly identical after careful review, accept it but reduce confidence to 0.80 (valid but unusual)

2. SEQUENCE LOGIC:
   Expected patterns (normal):
   - Consecutive: 41 → 42 → 43 (standard)
   - Skip ahead: 41 → 42 → 44 (page 43 unnumbered, acceptable)
   - Roman to Arabic: viii → ix → 1 (front matter to body transition, normal)

   Suspicious patterns (re-examine your extraction):
   - Duplicate: 41 → 42 → 42 (LIKELY ERROR - check image again)
   - Reversal: 41 → 40 → 42 (LIKELY ERROR - check if "40" is actually "43")
   - Large gap: 41 → 42 → 67 (unusual unless major section boundary)

3. STYLE CONSISTENCY:
   - If previous 5 pages used arabic numerals, current should too (unless region boundary)
   - If previous 5 pages had numbers in footer-right, current should too
   - Sudden style changes suggest extraction error, not actual page design change

Use these checks to adjust confidence, not to override clear visual evidence.
If validation fails but visual evidence is clear, keep the extraction but reduce confidence.
</page_number_extraction>

<page_region_classification>
Classification uses position-based defaults that can be overridden by content evidence.

Default classification by position (pdf-page X of Y total):
- Early pages of document: front_matter (confidence 0.90)
- Middle portion of document: body (confidence 0.90)
- Final pages of document: back_matter (confidence 0.85)

Override defaults with HIGHER confidence (0.95) using these content signals:

Strong override signals (prefer these over position):
1. Roman numeral page numbers → front_matter (confidence 0.95)
   - Overrides position even if beyond early pages
2. Arabic numerals starting at "1" → likely body (confidence 0.95)
   - Overrides position even if in early pages
   - Body content typically starts with page 1
3. Table of Contents layout → toc_area (confidence 0.95)
   - Multi-column, dot leaders, hierarchical titles
4. Index/Bibliography content → back_matter (confidence 0.95)
   - Alphabetical entries, references, citations

Decision hierarchy:
1. Content evidence (0.95 confidence) generally beats position (0.90 confidence)
2. Numbering style (roman/arabic) is the strongest content signal
3. Use "uncertain" only if conflicting content signals present (rare)

Region type definitions:
- front_matter: Title page, copyright, dedication, preface, introduction (often roman page numbers)
- toc_area: Table of Contents (distinctive multi-column layout with hierarchical titles)
- body: Main content chapters (typically arabic page numbers starting at 1)
- back_matter: Index, bibliography, endnotes, appendix (may be unnumbered)
- uncertain: Position-based default contradicted by content (use sparingly)

Example: Page in early portion with printed "1" → Likely "body" not "front_matter" (confidence 0.95)
</page_region_classification>

<block_classification>
Available block types by category:

Front and back matter:
- TITLE_PAGE, COPYRIGHT, DEDICATION, TABLE_OF_CONTENTS, PREFACE, INTRODUCTION

Main content:
- CHAPTER_HEADING, SECTION_HEADING, BODY, QUOTE, EPIGRAPH

Reference material:
- FOOTNOTE, ENDNOTES, BIBLIOGRAPHY, INDEX

Special elements:
- HEADER, FOOTER, PAGE_NUMBER, ILLUSTRATION_CAPTION, TABLE

Additional types:
- OCR_ARTIFACT, MAP_LABEL, DIAGRAM_LABEL, PHOTO_CREDIT

Fallback (use rarely, under 2%):
- OTHER

Classification decision tree (evaluate in order):

1. Check indentation first (primary structural signal):
   - Indented both sides: QUOTE (confidence 0.90+)
   - Centered text: CHAPTER_HEADING, EPIGRAPH, or DEDICATION
   - Hanging indent: BIBLIOGRAPHY entry

2. Check vertical position on page:
   - Top 10% of page: HEADER or CHAPTER_HEADING
   - Bottom 20% of page: FOOTNOTE, FOOTER, or PAGE_NUMBER

3. Check font size relative to body text:
   - 2x or larger than body: CHAPTER_HEADING
   - Larger or bold: SECTION_HEADING
   - Smaller than 8pt: FOOTNOTE, PHOTO_CREDIT, or FOOTER

4. Check content keywords:
   - Contains "Chapter", "Part": CHAPTER_HEADING
   - Contains "Index", "Bibliography": Use specific type
   - Garbled or corrupted: OCR_ARTIFACT

Confidence score guidelines:
- 0.95-1.0: Multiple clear signals agree
- 0.85-0.94: Most signals agree with minor ambiguity
- 0.70-0.84: Some conflicting signals or ambiguity
</block_classification>

<output_requirements>
Return structured JSON with:
- printed_page_number (extracted book-page number)
- page_region classification with confidence
- Block classifications with per-block confidence
- Must output exactly the same number of blocks as in the OCR data
- Each block must preserve the block_num from OCR data

Focus on visual and structural signals from the image. Do not correct or modify OCR text.
</output_requirements>"""


def build_user_prompt(ocr_page, ocr_text, current_page, total_pages, book_metadata, prev_page_number=None):
    """
    Build the user prompt with OCR data and document context.

    The page image is attached separately via the multimodal API
    and sent alongside this text prompt for vision-based analysis.

    Args:
        ocr_page: OCRPageOutput object
        ocr_text: Pre-formatted OCR text (JSON string from ocr_page.model_dump())
        current_page: Current page number (PDF sequence)
        total_pages: Total pages in document
        book_metadata: Book metadata dict
        prev_page_number: Previous page's extracted printed_page_number (for sequence validation)

    Returns:
        str: User prompt for the LLM
    """
    # Extract metadata fields with defaults
    title = book_metadata.get('title', 'Unknown')
    author = book_metadata.get('author', 'Unknown')
    year = book_metadata.get('year', 'Unknown')
    book_type = book_metadata.get('type', 'Unknown')

    # Calculate position in document
    percent_through = (current_page / total_pages * 100) if total_pages > 0 else 0

    # Count blocks for explicit instruction
    num_blocks = len(ocr_page.get('blocks', []))

    # Format previous page number context for sequence validation
    prev_context = ""
    if prev_page_number is not None:
        prev_context = f"\nPrevious page's printed number: {prev_page_number} (use for sequence validation)"

    return f"""<document_context>
Title: {title}
Author: {author}
Year: {year}
Type: {book_type}
</document_context>

<page_context>
PDF page {current_page} of {total_pages} ({percent_through:.1f}% through document)
Position suggests: {get_default_region(percent_through)} region{prev_context}
</page_context>

<important_reminder>
The PDF page number ({current_page}) is our internal file sequence. The book-page number (printed on the image) may be completely different or missing. Extract book-page from the image, not the PDF page number.
</important_reminder>

<ocr_data>
Below is the OCR data in JSON format. It contains {num_blocks} blocks detected by the OCR engine.
Each block has a block_num, bounding box (bbox), and paragraphs with text content.

{ocr_text}
</ocr_data>

<tasks>
1. Extract printed book-page number from image (ignore PDF page {current_page})
2. Classify page region using position-based defaults, override if content contradicts
3. Classify each of the {num_blocks} OCR blocks using decision tree (check indentation first)
4. Provide confidence scores for all classifications

IMPORTANT: Your output must contain exactly {num_blocks} blocks, preserving the block_num from each OCR block.
Do not merge, split, or skip any blocks. Each OCR block gets one classification.

Focus on visual and structural signals from the image.
</tasks>"""


def get_default_region(percent_through):
    """
    Helper to determine default region based on position in document.

    Uses qualitative position descriptions rather than hard thresholds.

    Args:
        percent_through: Percentage through the document (0-100)

    Returns:
        str: Default region name with qualitative description
    """
    if percent_through <= 15:
        return "front_matter (early pages)"
    elif percent_through >= 85:
        return "back_matter (final pages)"
    else:
        return "body (middle portion)"
