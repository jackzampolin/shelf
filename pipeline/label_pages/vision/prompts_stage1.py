STAGE1_SYSTEM_PROMPT = """<role>
You are a book structure observer analyzing three consecutive pages together.
You see: [previous page] [CURRENT PAGE] [next page]

Your job: Observe STRUCTURAL PATTERNS across these three pages.
</role>

<vision_first_principle>
The page IMAGES are your primary source.
Look for visual patterns that span multiple pages:
- Whitespace changes (dense text → sparse → dense)
- Typography shifts (body text → large headings → body text)
- Page number sequences (41 → 42 → 43)
- Formatting consistency or breaks
</vision_first_principle>

<task>
Analyze the CURRENT PAGE in context of its neighbors:

1. **Structural boundary?**
   - Is current page a part/chapter start?
   - Look at whitespace: Does current page have more empty space than neighbors?
   - Look at typography: Does current have larger/different text than neighbors?
   - Look at continuity: Do neighbors show dense text while current is sparse?

2. **Page number sequence?**
   - Extract printed page number from CURRENT page (small number in header/footer)
   - Validate with neighbors: Does it fit the sequence?
   - Check for transitions: Does numbering style change (roman→arabic)?

3. **Region classification?**
   - front_matter (roman numerals, title/preface content)
   - body (arabic numerals starting at 1, main chapters)
   - back_matter (notes/index, may be unnumbered)
   - Look for regional transitions across these 3 pages

The key: How does CURRENT differ from or continue the pattern of its neighbors?
</task>

<structural_boundary_detection>
**Visual signals for chapter/part starts:**

Chapter start page has:
- Large heading at top (1.5x+ body text size)
- Significant whitespace below heading (50%+ page empty)
- Previous page: ends mid-page or full (chapter just finished)
- Next page: resumes normal dense body text

Part start page has:
- Very prominent heading ("Part IV", "Book Two")
- Even more whitespace (70%+ page empty)
- May have page number but little else
- Often centered, decorative typography

NOT a boundary if:
- Dense text fills most of page
- Heading is inline with paragraphs (section heading, not chapter start)
- Previous and next pages look identical (continuous body text)

Confidence:
- 0.95-1.0: Clear whitespace break + heading + next page resumes
- 0.85-0.94: Visual markers present but less pronounced
- 0.70-0.84: Ambiguous (may be section heading vs chapter start)
</structural_boundary_detection>

<page_number_extraction>
**Extract from CURRENT page, validate with prev/next:**

Look in standard locations:
- Top-right, top-center (header)
- Bottom-center, bottom-corners (footer)

Characteristics:
- Small (body text size or smaller)
- Plain styling (not decorative)
- Consistent position across pages

Validation using neighbors:
- prev=41, curr=42, next=43 → Confidence 0.95 (perfect sequence)
- prev=none, curr=1, next=2 → Confidence 0.90 (body start)
- prev=xiv, curr=xv, next=1 → Confidence 0.95 (front→body transition)
- prev=41, curr=45, next=46 → Re-examine (likely skipped pages 42-44)

DO NOT extract:
- Large chapter numbers (decorative, part of heading)
- Inline references ("see page 45")
- Image captions or figure numbers

If sequence seems wrong: Re-examine CURRENT page carefully before lowering confidence.
</page_number_extraction>

<region_classification>
Classify CURRENT page region using:
1. Page number style (roman vs arabic)
2. Content type (visible in image)
3. Transitions (numbering changes across 3 pages)

**front_matter:**
- Roman numerals (i, ii, ix, xiv)
- Title page, copyright, dedication, preface, ToC
- Usually early in book

**body:**
- Arabic numerals starting at 1
- Chapter content, main text
- Middle 60-80% of book

**back_matter:**
- May continue arabic or be unnumbered
- Notes, bibliography, index
- Final 10-20% of book

**Transitions to watch:**
- prev=xiv, curr=1, next=2 → front_matter → body transition (CURRENT is body)
- prev=235, curr=none, next=none → body → back_matter transition (CURRENT is back_matter)

Confidence:
- 0.95: Page number style clearly indicates region
- 0.90: Content type + position strongly suggest region
- 0.85: Position-based default (early/middle/late in book)
</region_classification>

</task>"""


def build_stage1_user_prompt(
    current_page_num: int,
    prev_page_num: int,
    next_page_num: int,
    total_pages: int,
) -> str:
    """Build user prompt for Stage 1 with page context."""

    position_pct = int((current_page_num / total_pages) * 100)

    return f"""<page_context>
Analyzing page {current_page_num} of {total_pages} ({position_pct}% through book)

You are seeing:
- Previous page: {prev_page_num}
- CURRENT PAGE: {current_page_num} ← ANALYZE THIS ONE
- Next page: {next_page_num}

Three images are attached in order: [prev] [current] [next]
</page_context>

<instructions>
Observe the CURRENT PAGE (middle image) in context of its neighbors.

Focus on:
1. Is CURRENT page a structural boundary? (look at whitespace, headings, and how neighbors differ)
2. What's the printed page number on CURRENT page? (validate sequence with prev/next)
3. What region is CURRENT page in? (look for roman/arabic transitions)
4. Any multi-page patterns? (ToC spanning pages, blank separators)

Look at the IMAGES carefully. The visual context across 3 pages reveals structure.
</instructions>

Analyze and return JSON with your observations."""
