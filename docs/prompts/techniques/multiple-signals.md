# Multiple Overlapping Signals

**Principle:** Triangulate Truth from Multiple Sources

## The Problem

Single information sources are unreliable:
- OCR errors (Roman numerals: "VIII" → "Vil")
- Boundaries mislabeled (heading preview truncated)
- Grep noise (scattered mentions vs. actual chapter)
- Vision ambiguous (running header or boundary?)

**Trusting one source → errors propagate.**

## The Solution

Use multiple independent signals that confirm each other. Like a detective: gather evidence, cross-check, find where signals align.

```
Boundaries say: Page 91 has "Chapter Vil"
Sequence reasoning: Page 89 is "VII", page 95 is "IX" → 91 should be "VIII"
Grep shows: Dense cluster pages 91-94
Vision confirms: Image shows "VIII" (OCR error)
```

**Overlapping signals agree → High confidence.**

## When to Use

- High-stakes decisions (finding critical content)
- When individual signals are noisy or error-prone
- Detective-style search tasks (finding ToC entries)
- Verification and validation scenarios

## How to Apply

1. **Identify available signals**: What information sources exist?
2. **Describe what each reveals**:
   - Boundaries: Curated, clean, but might miss entries
   - Grep: Noisy, but density reveals truth
   - OCR: Actual text, but errors in Roman numerals
   - Vision: Ground truth, but expensive
3. **Teach cross-verification**: "Do signals agree? Contradict?"
4. **Build detective reasoning**: "If X says A but Y says B, what's the truth?"
5. **Prioritize by reliability**: Which signal to trust when they conflict?

## Detective Workflow

```
1. LANDSCAPE (boundaries): See known section starts
   → Strength: Targeted, curated
   → Limitation: Might miss entries, previews truncated

2. SEARCH (grep): Find text across entire book
   → Strength: Complete coverage, density reveals structure
   → Limitation: Noisy, OCR errors propagate

3. INSPECT (OCR): Read actual text on candidate pages
   → Strength: Confirms what previews suggest
   → Limitation: Errors in Roman numerals, small text

4. VISUAL (image): See the page when text fails
   → Strength: Ground truth, catches OCR errors
   → Limitation: Expensive ($0.001/image)
```

**Start cheap (boundaries, grep), escalate to expensive (vision) only when needed.**

## Codebase Example

`pipeline/link_toc/agent/prompts.py:6-20, 22-54`

```python
<search_philosophy>
Your advantage: Multiple overlapping signals that can confirm each other.

Think of it like detective work:
- LANDSCAPE: See the known boundaries (curated, clean, but might miss some)
- SEARCH: Look for your text across the whole book (noisy, but density reveals truth)
- INSPECT: Read actual text to verify candidates
- VISUAL: See the page when text alone isn't clear

Start targeted (boundaries), expand if needed (grep), always confirm (OCR),
use vision liberally (cheap, catches errors).
</search_philosophy>

# Later, each tool described:
**list_boundaries()** - Strength: Targeted / Limitation: Might miss
**grep_text()** - Strength: Density patterns / Limitation: Noisy
**get_page_ocr()** - Strength: Actual text / Limitation: Errors
**view_page_image()** - Strength: Ground truth / Limitation: Cost
```

## Signal Agreement Patterns

**High confidence (signals align):**
```
Boundaries: Page 45 "Chapter XIII"
Grep: Dense cluster pages 45-62 (5 matches each)
OCR: "Chapter XIII: The War Years"
→ All signals agree → confidence 0.95
```

**Medium confidence (partial alignment):**
```
Boundaries: Page 45 "Chapter X..." (truncated)
Grep: Dense cluster pages 45-62
OCR: "Chapter XIII" (different from preview)
→ Grep + OCR agree, boundary unclear → confidence 0.85
```

**Low confidence (conflict):**
```
Boundaries: Page 45 "Chapter Vil" (OCR error)
Grep: Sparse matches (1-2 per page)
OCR: Same error "Vil"
Vision: Shows "VIII" (actual)
→ Signals conflict → confidence 0.70
```

## Why This Works

**No single source is perfect:**
- Boundaries curated but incomplete
- Grep complete but noisy
- OCR fast but error-prone
- Vision accurate but expensive

**Multiple signals triangulate truth:**
- Agreement increases confidence
- Conflict triggers escalation (use vision)
- Each signal reveals different aspect

**Like GPS triangulation: More satellites → Better fix.**

## Anti-Pattern

```
❌ Single signal, no cross-check:
"Search boundaries for 'Chapter XIII'. If found, return page."

→ Misses entries not in boundaries
→ Can't catch OCR errors
→ No confidence calibration
```

```
✅ Multiple overlapping signals:
"1. Check boundaries (targeted)
 2. If unclear, grep for density
 3. Confirm with OCR
 4. Use vision if OCR errors suspected
Cross-check signals, build confidence."

→ Catches errors, high confidence when aligned
```

## Related Techniques

- `vision-first-workflow.md` - One of the signals
- `grep-guided-attention.md` - Another signal
- `density-reasoning.md` - Grep signal interpretation
- `confidence-calibration.md` - Use agreement to calibrate
- `cost-awareness.md` - Cheap signals first
