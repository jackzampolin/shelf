# Vision-First Workflow

**Principle:** Triangulate Truth from Multiple Sources

## The Problem

Multimodal prompts (image + text) without clear guidance create confusion:
- When to trust the image vs. OCR text?
- What does each source reveal?
- How to combine them?

**Result:** Model uses sources inconsistently, makes errors.

## The Solution

Explicitly assign what each source reveals. Clarify the workflow.

```
IMAGE shows: Structure, layout, indentation, spacing, styling
OCR TEXT provides: Accurate content, what the words actually are

Workflow: See image (structure) → Use OCR (content) → Combine
```

**Result:** Model uses each source for its strength, combines effectively.

## When to Use

- Any multimodal prompt (image + text input)
- Tasks requiring layout understanding (ToC extraction, boundary detection)
- When OCR text quality varies (poor scans, formatting, small text)

## How to Apply

1. **Present both sources clearly**: "You have IMAGE + OCR TEXT"
2. **Specify what each reveals**:
   - Image: Visual structure, spatial relationships, styling
   - OCR: Text content, what it says
3. **Guide the workflow**: See → Extract → Verify
4. **Make it explicit**: "Use X for Y, use Z for W"

## Source Assignment

**What IMAGE reveals (structure):**
- Indentation levels (hierarchy)
- Spacing and alignment (visual organization)
- Styling (bold, large, small)
- Visual density (sparse vs. dense)
- Spatial relationships (what's near what)

**What OCR TEXT reveals (content):**
- Accurate words (what it says)
- Entry titles (text content)
- Page numbers (numeric values)
- Keywords (searchable text)

**Combined:**
- Image tells you WHERE and HOW (structure)
- OCR tells you WHAT (content)

## Codebase Example

`pipeline/extract_toc/detection/prompts.py:9-22`

```python
<critical_instructions>
You have TWO sources of information:
1. **VISUAL LAYOUT** (image): Shows hierarchy through indentation, styling, positioning
2. **CLEAN OCR TEXT**: Accurate text extraction (use this for entry content)

Your goal: Extract complete ToC entries (title + page number + hierarchy level) in a single pass.

HIERARCHY DETERMINATION:
- Use VISUAL CUES (indentation, styling, size) to determine entry level
- Level 1: Top-level entries (flush left or minimally indented, often bold/large)
- Level 2: Nested entries (moderate indent, sub-entries under Level 1)

Use OCR text for WHAT (the content), use IMAGE for WHERE and HOW (the structure).
</critical_instructions>
```

**Note:** Explicit assignment: Visual → structure, OCR → content.

## The Workflow

```
STEP 1: See image (structure)
→ Look at visual layout
→ Identify indentation levels
→ Notice styling (bold, large)
→ Observe spacing patterns

STEP 2: Read OCR (content)
→ Get accurate text
→ Extract entry titles
→ Find page numbers

STEP 3: Combine (complete extraction)
→ Visual hierarchy → Level assignment
→ OCR content → Title and page number
→ Result: Structured entry with all fields
```

## Why Each Source Matters

**Image alone (insufficient):**
- Can see structure, but reading text directly from images is error-prone
- Small text hard to read
- OCR already extracted the text more accurately

**OCR alone (insufficient):**
- Has the words, but no spatial information
- Can't see indentation levels
- Can't distinguish hierarchy

**Image + OCR (complete):**
- Image provides structure
- OCR provides content
- Combined: Complete understanding

## Anti-Pattern

```
❌ Unclear source guidance:
"Look at the page and extract the table of contents entries."

→ Model confused: Should I read text from image or use OCR?
→ Inconsistent use of sources
→ Errors in hierarchy detection
```

```
✅ Explicit source assignment:
"Use IMAGE to see indentation levels (hierarchy).
 Use OCR TEXT to get accurate entry titles.
 Combine: Visual hierarchy + OCR content = Complete entry."

→ Model uses each source for its strength
→ Consistent, accurate extraction
```

## Source Trust Hierarchy

**For structure (WHERE/HOW):**
1. Image (ground truth for layout)
2. Spatial analysis (indentation, alignment)

**For content (WHAT):**
1. OCR text (most accurate for words)
2. Image (only when OCR fails - small text, errors)

**When OCR has errors:**
- Use image to verify
- Common in: Roman numerals, small text, formatting

**Example:** `pipeline/link_toc/agent/prompts.py:185-187`
```python
Use vision liberally (cheap at $0.001, catches OCR errors)
```

## Related Techniques

- `multiple-signals.md` - Vision is one of several signals
- `grep-guided-attention.md` - Use grep to identify pages, then vision
- `cost-awareness.md` - Vision costs money, use strategically
