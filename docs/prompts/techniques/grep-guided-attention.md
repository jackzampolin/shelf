# Grep-Guided Attention

**Principle:** Triangulate Truth from Multiple Sources

## The Problem

Vision models can miss small text or specific keywords without guidance. Searching 500 pages sequentially is slow and expensive.

**Unguided search:**
- Load page 1, scan for ToC → not found
- Load page 2, scan for ToC → not found
- Load page 3, scan for ToC → not found
- ... (repeat 500 times)

**Cost:** $0.50, slow, wasteful.

## The Solution

Use cheap text search (grep) to find keyword hints, then load only candidate pages for visual verification.

**Grep-guided search:**
- Grep for "Table of Contents" → pages 5, 6, 7 identified
- Load only pages 5-7 for visual verification
- Found ToC on page 5 → stop

**Cost:** $0.003, fast, targeted.

## When to Use

- Searching large documents for specific content
- Finding pages with particular patterns (ToC, chapter starts, appendices)
- When small text or specific keywords are critical
- Cost optimization (grep is free, vision costs money)

## How to Apply

1. **Grep first**: Run cheap keyword search across all text
2. **Present results**: Show model which pages have keywords
3. **Load strategically**: Only load candidate pages identified by grep
4. **Verify visually**: Confirm what grep suggested
5. **Cross-check**: Does visual match grep hint?

## The Pattern

```
STEP 1: Grep (FREE)
→ Search for keywords: "Table of Contents", "Contents", "Chapter"
→ Results: Pages 5, 6, 7 have "Contents"
          Pages 45, 89 have "Chapter"

STEP 2: Load candidates (CHEAP)
→ Load images for pages 5, 6, 7 only
→ Visual verification: Page 5 is ToC, pages 6-7 continuation

STEP 3: Stop (DONE)
→ Found ToC at pages 5-7, no need to load more images
```

**Total cost:** 3 images ($0.003) vs. 500 images ($0.50)

## Codebase Example

`pipeline/find_toc/agent/prompts.py:29-40`

```python
<tool_workflow>
STEP 1: Get Grep Report (FREE - no cost)
→ Call get_frontmatter_grep_report()
→ Returns pages where keywords appear:
  - toc_candidates: Pages with "Table of Contents", "Contents", etc.
  - front_matter: Pages with "Preface", "Introduction", etc.
  - structure: Pages with "Chapter", "Part" patterns

STEP 2: DISCOVER ToC Range (one page at a time)
→ Use load_page_image() to explore candidates one by one
→ WORKFLOW: See → Document discovery → Load next → Repeat

REMEMBER: Grep finds TEXT hints, Vision confirms STRUCTURE
</tool_workflow>
```

**Note:** Explicit "FREE - no cost" label + workflow: grep → vision.

## What Grep Reveals

**Direct matches (high signal):**
- `toc_candidates`: Pages with "Table of Contents", "Contents"
- Usually accurate, high precision

**Structural clustering (strong signal):**
- `structure`: Pages with "Chapter", "Part", "Section"
- Dense clustering in front matter = likely ToC
- Pattern: Many "Chapter X" mentions on 1-2 pages = ToC listing chapters

**Context (supporting signal):**
- `front_matter`: Pages with "Preface", "Introduction"
- ToC often appears near these sections

## Grep Interpretation

From `pipeline/find_toc/agent/prompts.py:141-165`:

```python
<grep_report_interpretation>
**toc_candidates**: Direct ToC keyword matches (highest priority)
- If found: Check these pages first

**structure**: Chapter/Part clustering (STRONG signal in front matter!)
- Dense clustering of structural keywords on 1-2 consecutive pages → LIKELY THE TOC
- Pattern: Dense clustering = ToC listing; Sparse scattered = body text

**front_matter**: Preface/introduction markers
- Use for context: ToC often appears before/after these sections

**Decision patterns:**
- toc_candidates + structure clustering at same page → Very high confidence
- structure clustering on consecutive pages (no toc_candidates) → Load clustered pages
- All signals absent → Sequential scan of front matter region
</grep_report_interpretation>
```

## Why This Works

**Economic reasoning:**
- Grep is FREE (text search on already-extracted OCR)
- Vision is $0.001 per image
- Most books: ToC in first 20 pages
- Grep narrows 500 pages → 3-5 candidates
- **100x cost reduction**

**Attention guidance:**
- Models can miss small text without hints
- Grep says "this page has the keyword"
- Model looks specifically at that page
- Cross-verification: keyword present + visual structure = ToC

## Anti-Pattern

```
❌ Sequential image scanning:
"Load pages 1, 2, 3... until you find ToC."

→ Expensive: $0.50 (500 images)
→ Slow: 500 API calls
→ Unguided: No targeting
```

```
✅ Grep-guided search:
"1. Grep for ToC keywords (free)
 2. Load only candidates (3-5 images)
 3. Verify visually
 4. Stop when found"

→ Cheap: $0.003 (3 images)
→ Fast: 3 API calls
→ Targeted: High probability pages
```

## Related Techniques

- `cost-awareness.md` - Economic rationale for grep-first
- `density-reasoning.md` - Interpret grep match counts
- `multiple-signals.md` - Grep is one of several signals
- `vision-first-workflow.md` - What to do after grep identifies candidates
