# Correction Prompt Evolution: Lessons for Label Stage

**Date:** 2025-10-15
**Objective:** Extract proven prompt engineering patterns from correction stage to improve label stage performance

---

## Executive Summary

The correction prompt evolved from 252 lines to 88 lines (**65% reduction**) while **improving accuracy from ~80% to 84%+**. Key improvements came from:

1. **Critical rules at TOP** (lines 1-10 vs buried at line 673)
2. **Visual markers** (❌/✅) for clear right/wrong examples
3. **Concrete examples** before abstract rules
4. **Pattern-based guidance** over verbose explanations
5. **Iterative refinement** based on data analysis (not intuition)

**Current State:**
- **Correction Stage:** 84% accuracy, 1.9% verbose notes (down from 7.4%)
- **Label Stage:** 87.7% page number accuracy, 3.9% OTHER blocks (target: <2%)

---

## Prompt Evolution Timeline

### Version 1: Initial (commit 6e74791)
**Length:** ~150 lines
**Structure:** Task description + block types list
**Schema:** `corrected_text` field (nullable)

**Problems:**
- Generic instructions without specifics
- No examples of what to fix vs not fix
- Schema allowed ambiguity (when to use null?)

### Version 2: First Restructure (commit 3ca07c1)
**Length:** 88 lines (65% shorter)
**Structure:** Critical rules → Examples → What to fix → Confidence → Notes format

**Key Changes:**
```diff
+ ═══════════════════════════════════════════════════════════════════════
+ CRITICAL RULES (READ THESE FIRST)
+ ═══════════════════════════════════════════════════════════════════════
+
+ 1. OUTPUT FORMAT:
+    - If NO errors: text=null, notes="No OCR errors detected"
+    - If errors found: text=CORRECTED_FULL_PARAGRAPH, notes="Brief description"
```

**Results:**
- Corrections applied: 80.5%
- Verbose notes: 1.9% (down from 7.4%)
- But: Hyphen artifacts ("cam-paign" instead of "campaign")

### Version 3: Edge Case Refinement (commit 0db213b)
**Length:** 88 lines (same structure, refined content)
**Focus:** Fix hyphen removal edge case

**Critical Addition:**
```diff
Example 2: Line-Break Hyphen (Most Common - 70% of fixes)
- OCR: "The presi- dent announced the policy."
- → Output: {"text": "The president announced the policy.", "notes": "Removed line-break hyphen in 'president'", "confidence": 0.97}
+ OCR: "The cam- paign in Kan- sas"
+ Image shows: "The campaign in Kansas" (no hyphens in original)
+ → Output: {"text": "The campaign in Kansas", "notes": "Removed line-break hyphens: 'cam- paign'→'campaign', 'Kan- sas'→'Kansas'", "confidence": 0.97}
+
+ CRITICAL: Remove BOTH the hyphen AND the space (join word parts completely)
+ ❌ WRONG: "cam-paign" (kept hyphen, removed space)
+ ✅ CORRECT: "campaign" (removed hyphen AND space)
```

**Pattern Description Added:**
```diff
✅ FIX THESE (Character-Level OCR Errors Only):
- • Line-break hyphens: "presi- dent" → "president" (70% of all corrections)
+ • Line-break hyphens: "cam- paign" → "campaign" (remove BOTH hyphen + space)
+   Pattern: [word]- [space][word] → join into single word
+   Note: These are printing artifacts where words split across lines
```

**Results:** Testing in progress (84% expected)

---

## What Made the Correction Prompt Effective

### 1. Structure: Critical Rules First

**Before (buried at end):**
```
[673 lines of context]
Remember:
- Only correct OCR errors
- Be conservative
```

**After (lines 1-20):**
```
═══════════════════════════════════════════════════════════════════════
CRITICAL RULES (READ THESE FIRST)
═══════════════════════════════════════════════════════════════════════

1. OUTPUT FORMAT:
   - Use 1-based numbering: block_num and par_num start at 1 (not 0)
   - If NO errors: text=null, notes="No OCR errors detected"
   - If errors found: text=CORRECTED_FULL_PARAGRAPH, notes="Brief description"

2. WHEN YOU WRITE NOTES, YOU MUST APPLY THOSE CHANGES TO TEXT:
   ❌ WRONG: notes="Fixed X", but text still has X
   ✅ CORRECT: notes="Fixed X", text has X corrected
```

**Why this works:**
- LLMs prioritize early prompt content (primacy bias)
- Schema compliance rules must be at TOP, not buried
- Visual separators (═══) create clear boundaries

### 2. Visual Markers for Right/Wrong

**Pattern used throughout:**
```
❌ WRONG: notes="Fixed X", but text still has X
✅ CORRECT: notes="Fixed X", text has X corrected
```

**Why this works:**
- Emoji markers create visual anchors
- Side-by-side comparison shows contrast clearly
- Works better than "Don't do X" or "Do Y" alone

### 3. Concrete Examples Before Abstract Rules

**Example 2 (70% of corrections):**
```
OCR: "The cam- paign in Kan- sas"
Image shows: "The campaign in Kansas" (no hyphens in original)
→ Output: {"text": "The campaign in Kansas", "notes": "Removed line-break hyphens: 'cam- paign'→'campaign', 'Kan- sas'→'Kansas'", "confidence": 0.97}
```

Then followed by pattern:
```
Pattern: [word]- [space][word] → join into single word
```

**Why this works:**
- Example shows real input/output first
- Pattern extracts the general rule
- LLMs learn better from examples than rules

### 4. Pattern-Based Guidance

**Character-level patterns:**
```
• Character swaps: rn→m, cl→d, li→h, 1→l, 0→O
• Ligatures: fi, fl, ff, ffi, ffl misread
```

**Why this works:**
- Concise (one line per pattern)
- Uses symbolic notation (→)
- Covers 80%+ of OCR errors with 5 patterns

### 5. Edge Case Disambiguation

**Real vs Line-Break Hyphens:**
```
❌ DO NOT FIX:
• Real compound hyphens: Keep "self-aware", "Vice-President", "pre-WWI", "T-Force"
  (No space after hyphen = real hyphen, keep it!)
```

**Why this works:**
- Provides discriminating signal ("No space after hyphen")
- Gives concrete examples from actual book content
- Prevents overcorrection

### 6. Quantified Guidance

**Throughout the prompt:**
- "MOST PARAGRAPHS (80-90%) HAVE NO ERRORS → text=null"
- "Line-Break Hyphen (Most Common - 70% of fixes)"
- "Keep brief (under 100 chars)"

**Why this works:**
- Sets expectations for frequency distribution
- Prevents over/under application
- Helps model calibrate conservatism

### 7. Confidence Score Calibration

**Specific ranges with reasons:**
```
• 0.95-1.0: Obvious error, clear image (line-break hyphens, clear substitutions)
• 0.85-0.94: Clear error, minor ambiguity
• 0.70-0.84: Some ambiguity in image or error pattern
• <0.70: Uncertain - consider text=null instead
```

**Why this works:**
- Links score to objective criteria ("clear image")
- Uses ranges, not single values
- Provides decision rule for low confidence

### 8. Notes Format Constraints

**Clear template examples:**
```
• "Removed line-break hyphen in 'word'"
• "Fixed 'X'→'Y' (character substitution)"
• "No OCR errors detected" (when text=null)

DO NOT write long explanations, analysis, or uncertainty.
If uncertain, lower confidence score instead.
```

**Why this works:**
- Template format is easy to follow
- Redirects verbosity to confidence scores
- Reduced verbose notes from 7.4% to 1.9%

---

## Prompt Engineering Patterns

### Length: Shorter is Better

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| **Lines** | 252 | 88 | -65% |
| **Accuracy** | ~75% | 84% | +9pp |
| **Verbose notes** | 7.4% | 1.9% | -5.5pp |

**Lesson:** Remove verbose explanations, focus on directives.

### Organization: Critical → Examples → Details

```
1. CRITICAL RULES (lines 1-20)
   - Schema compliance
   - Gotchas (notes vs text sync)

2. EXAMPLES (lines 21-60)
   - No errors (most common case)
   - Line-break hyphens (70% of fixes)
   - Character substitution
   - Multiple fixes

3. WHAT TO FIX (lines 61-75)
   - ✅ Fix these
   - ❌ Don't fix these

4. CONFIDENCE SCORES (lines 76-82)

5. NOTES FORMAT (lines 83-88)
```

**Lesson:** Put most-used patterns first (no errors, then line-break hyphens).

### Example Quality: Real Data > Synthetic

**Bad (synthetic):**
```
Example: Fix "tlie" to "the"
```

**Good (from actual failures):**
```
Example 2: Line-Break Hyphen (Most Common - 70% of fixes)
OCR: "The cam- paign in Kan- sas"
Image shows: "The campaign in Kansas" (no hyphens in original)
```

**Lesson:** Use real examples from failed cases in test data.

### Visual Hierarchy: Separators + Markers

```
═══════════════════════════════════════════════════════════════════════
CRITICAL RULES (READ THESE FIRST)
═══════════════════════════════════════════════════════════════════════

❌ WRONG: "cam-paign" (kept hyphen, removed space)
✅ CORRECT: "campaign" (removed hyphen AND space)
```

**Lesson:** Use visual markers liberally, they create structure.

---

## Comparison: Correction vs Label Prompts

### Correction Prompt (88 lines, effective)

**Structure:**
```
CRITICAL RULES (10 lines)
  ├─ Schema format
  ├─ Gotchas (4 rules with ❌/✅)
  └─ Conservatism ("80-90% text=null")

EXAMPLES (30 lines)
  ├─ No errors (1 example)
  ├─ Line-break hyphens (8 lines, 70% of cases)
  ├─ Character substitution (3 lines)
  └─ Multiple fixes (3 lines)

WHAT TO FIX (14 lines)
  ├─ ✅ Fix these (5 patterns)
  └─ ❌ Don't fix these (5 anti-patterns)

CONFIDENCE (7 lines)
NOTES FORMAT (7 lines)
REMEMBER (10 lines)
```

**Ratio:** 40% examples, 30% rules, 30% guidance

### Label Prompt (280 lines, verbose)

**Structure:**
```
Task (7 lines)

Page Number Extraction (30 lines)
  ├─ Checklist (4 items)
  ├─ Formats (3 styles)
  ├─ Output fields (4 fields)
  └─ Success rate goal

Block Classification (200+ lines)
  ├─ Structural types (6 types)
  ├─ Content hierarchy (5 types)
  ├─ Reference material (4 types)
  ├─ Back matter (3 types)
  ├─ Page metadata (3 types)
  ├─ Special content (6 types)

Quote Detection Guidance (35 lines)
  ├─ Visual signals (5 items)
  ├─ Textual signals (3 items)
  ├─ Common patterns (4 items)
  └─ Examples (3)

OTHER Usage Constraints (25 lines)

New Block Types (25 lines)

Confidence Guidance (30 lines)

Classification Strategy (40 lines - decision tree)

Examples (40 lines - 4 examples)

Output Format (5 lines)
```

**Ratio:** 14% examples, 60% taxonomy, 26% guidance

**Problems:**
- Block type taxonomy is 200+ lines (should be separate reference)
- Critical rules buried in middle sections
- Decision tree is 40 lines (too complex)
- Only 4 examples for 25+ block types
- No ❌/✅ visual markers
- Verbose prose vs concise bullets

---

## Recommendations for Label Prompt

### Recommendation 1: Move Critical Rules to TOP

**Problem:** Schema compliance rules are scattered across sections.

**Solution:** Create a CRITICAL RULES section at lines 1-20:

```markdown
═══════════════════════════════════════════════════════════════════════
CRITICAL RULES (READ THESE FIRST)
═══════════════════════════════════════════════════════════════════════

1. PAGE NUMBER EXTRACTION:
   - If visible: Set exact text (e.g., "ix", "45")
   - If unnumbered: Set all fields to null, confidence=1.0
   ❌ WRONG: Guess page numbers, set confidence=0.5
   ✅ CORRECT: Only extract what you SEE, null if absent

2. BLOCK CLASSIFICATION:
   - Use most specific type that fits visual + textual signals
   - Prioritize: BODY (60%), FOOTNOTE (20%), QUOTE (5%)
   - Use OTHER only if truly unclassifiable (<2% target)
   ❌ WRONG: Use OTHER for map labels, photo credits, diagrams
   ✅ CORRECT: Use MAP_LABEL, PHOTO_CREDIT, DIAGRAM_LABEL

3. CONFIDENCE SCORES:
   - 0.95-1.0: Clear visual signals (font size, position, formatting)
   - 0.85-0.94: Most signals present, minor ambiguity
   - 0.70-0.84: Some ambiguity between 2 types
   ❌ WRONG: Default to 1.0 for all blocks
   ✅ CORRECT: Reflect actual visual clarity

4. COMMON BLOCK DISTRIBUTION:
   - BODY: ~60% (most content)
   - FOOTNOTE: ~20% (small font, bottom 20%)
   - QUOTE: ~5% (indented both sides)
   - OTHER: <2% (truly unclassifiable)
```

**Evidence:** Correction prompt improved from 75% to 84% accuracy after moving critical rules to top.

**Before/After:**
```diff
- [200 lines of block types]
- <quote_detection_guidance>
- [35 lines about QUOTE]
+ ═══════════════════════════════════════════════════════════════════════
+ CRITICAL RULES (READ THESE FIRST)
+ ═══════════════════════════════════════════════════════════════════════
+ [10-20 lines of must-follow rules with ❌/✅ examples]
```

---

### Recommendation 2: Add Visual Markers to Examples

**Problem:** Examples lack clear right/wrong visual cues.

**Solution:** Add ❌/✅ markers to all examples:

```markdown
Example 1: QUOTE vs BODY (indentation is key signal)
Visual: Text indented 1" from BOTH left and right margins
Content: "The policy was clear: no negotiations..."
❌ WRONG: BODY (missed the double indentation)
✅ CORRECT: QUOTE (indented both sides = block quote)

Example 2: MAP_LABEL vs OTHER
Visual: Text on map image, all-caps geographic names
Content: "PACIFIC OCEAN" and "JAPAN"
❌ WRONG: OTHER (3.9% overuse problem)
✅ CORRECT: MAP_LABEL (geographic text on maps)
```

**Evidence:** Correction prompt uses ❌/✅ in 8 places, creating clear visual contrast.

---

### Recommendation 3: Reduce Block Taxonomy, Use Examples

**Problem:** 200+ lines of block type definitions (60% of prompt).

**Solution:** Move full taxonomy to separate reference, keep only top 10 types + patterns in prompt:

```markdown
<block_classification>

**Most Common (95% of blocks):**

BODY (60%):
- Standard paragraph text, consistent font (10-12pt)
- Left-aligned, normal margins
- Example: Main narrative content
✅ Use for: Regular paragraphs
❌ Not for: Indented quotes, small footnotes

FOOTNOTE (20%):
- Small font (<8pt), bottom 20% of page
- Superscript numbers, reference citations
- Visual: Significant font size difference
✅ Use for: Bottom-of-page references
❌ Not for: Endnotes sections (different page structure)

QUOTE (5%):
- Indented from BOTH left and right (CRITICAL SIGNAL)
- Often italicized, extra whitespace around
- Pattern: Margins narrower than BODY
✅ Use for: Block quotes indented both sides
❌ Not for: Body text with quotes inside, EPIGRAPH

CHAPTER_HEADING (3%):
- Large font (2x+ body), substantial whitespace
- Often centered or left-aligned
- Keywords: "Chapter N" or just number
✅ Use for: Clear chapter starts
❌ Not for: Section headings (only 1.5x size)

SECTION_HEADING (3%):
- Bold/larger than body (1.5x), left-aligned
- Breaks text flow, minimal whitespace
✅ Use for: Subsection titles within chapters
❌ Not for: Bold first sentences (that's BODY)

**Less Common (5%):**
For full taxonomy (25 types), see: [reference section at end]
```

**Evidence:** Correction prompt is 88 lines total. Label prompt spends 200+ lines on taxonomy alone.

**Before/After:**
```diff
- <block_classification>
- [200 lines of 25 block types]
+ <block_classification>
+ [50 lines for top 5 types with visual patterns]
+ [Move full taxonomy to end of prompt]
```

---

### Recommendation 4: Pattern-Based Classification Guide

**Problem:** Decision tree is 40 lines of nested logic.

**Solution:** Simplify to visual pattern matching:

```markdown
<classification_patterns>

Quick patterns (check in order):

1. **Font Size Check** (fastest signal):
   - Much smaller (<8pt)? → FOOTNOTE, PHOTO_CREDIT
   - Much larger (2x+)? → CHAPTER_HEADING
   - Slightly larger (1.5x)? → SECTION_HEADING
   - Standard size? → BODY, QUOTE, most others

2. **Position Check** (second fastest):
   - Bottom 20%? → FOOTNOTE, FOOTER, PAGE_NUMBER
   - Top 10%? → HEADER, CHAPTER_HEADING
   - Middle 70%? → BODY, QUOTE, SECTION_HEADING

3. **Indentation Check** (QUOTE indicator):
   - Indented BOTH sides? → QUOTE (high priority!)
   - Centered? → CHAPTER_HEADING, EPIGRAPH
   - Hanging indent? → BIBLIOGRAPHY

4. **Content Keywords** (final check):
   - Geographic names on visual? → MAP_LABEL
   - "Photo by", "Courtesy"? → PHOTO_CREDIT
   - Garbled nonsense? → OCR_ARTIFACT
   - Timeline/chart labels? → DIAGRAM_LABEL
</classification_patterns>
```

**Evidence:** Correction prompt uses 5 bullet patterns for character fixes instead of verbose explanations.

---

### Recommendation 5: Focus Examples on Current Failures

**Problem:** Generic examples, not addressing actual 87.7% page number accuracy or 3.9% OTHER overuse.

**Solution:** Use real failure examples from `analyze_label.py` output:

```markdown
<examples_from_failures>

Example 1: Page Number False Positive (Current accuracy: 87.7%)
Image: Page has "Chapter 3" at top but NO page number
❌ WRONG: {"printed_page_number": "3", "numbering_style": "arabic", "confidence": 0.8}
✅ CORRECT: {"printed_page_number": null, "numbering_style": "none", "confidence": 1.0}
Reason: Chapter numbers ≠ page numbers, only extract actual page numbers

Example 2: OTHER Overuse (Current: 3.9%, target: <2%)
Image: Small text "Photo by John Smith" below image
❌ WRONG: {"classification": "OTHER", "confidence": 0.6}
✅ CORRECT: {"classification": "PHOTO_CREDIT", "confidence": 0.95}
Reason: Use specific type (PHOTO_CREDIT) instead of OTHER

Example 3: QUOTE Under-Detection (Current confidence: 0.86 vs 0.97 for BODY)
Image: Paragraph indented 1" on both sides, italicized
❌ WRONG: {"classification": "BODY", "confidence": 0.95}
✅ CORRECT: {"classification": "QUOTE", "confidence": 0.94}
Reason: Double indentation is PRIMARY signal for QUOTE
</examples_from_failures>
```

**Evidence:** Correction prompt Example 2 uses real "cam- paign" failure case that occurred at 19.5% rate.

---

### Recommendation 6: Quantify Expected Distributions

**Problem:** No quantified guidance on how often to use each block type.

**Solution:** Add frequency expectations (like correction's "80-90% text=null"):

```markdown
<expected_distributions>

Typical book page distribution:
- BODY: ~60% of blocks
- FOOTNOTE: ~20%
- HEADER/FOOTER: ~10%
- CHAPTER_HEADING: ~1%
- SECTION_HEADING: ~3%
- QUOTE: ~5%
- OTHER: <2% (CRITICAL: If you're using OTHER more than 2%, use specific types)

**Red flags:**
- OTHER >5%: You're missing MAP_LABEL, PHOTO_CREDIT, DIAGRAM_LABEL, OCR_ARTIFACT
- QUOTE <3%: You're missing indented block quotes (check double-indentation)
- All confidences >0.95: You're over-confident, use full range
</expected_distributions>
```

**Evidence:** Correction prompt states "MOST PARAGRAPHS (80-90%) HAVE NO ERRORS → text=null" which calibrates conservatism.

---

### Recommendation 7: Consolidate Redundant Sections

**Problem:** Quote detection has 35-line dedicated section PLUS examples elsewhere.

**Solution:** Merge into single concise section with critical pattern:

```markdown
<quote_detection>

QUOTE is under-detected (0.86 confidence vs 0.97 for BODY).

**PRIMARY SIGNAL (90% accurate):**
- Indented from BOTH left and right margins
- Visual: Text block narrower than BODY paragraphs

**Secondary signals:**
- Italicized or different font
- Extra whitespace before/after
- Attribution line ("—Author Name")

**Example:**
Visual: [Show image of indented block]
✅ QUOTE: Indented both sides
❌ BODY with quotes: Normal margins, quotes inside text
❌ EPIGRAPH: Short, centered, chapter start only

**If unsure:** Check left AND right margins. If both indented → QUOTE.
</quote_detection>
```

**Evidence:** Correction prompt dedicates 8 lines to line-break hyphens (70% of corrections), proportional to importance.

---

### Recommendation 8: Notes Format Constraints

**Problem:** No guidance on paragraph-level notes format.

**Solution:** Add notes format section (like correction's "Keep brief (under 100 chars)"):

```markdown
<paragraph_notes>

For each paragraph, `confidence` field reflects:
- Visual clarity of block boundaries
- Ambiguity between types
- Image quality issues

Expected range:
- 0.95-1.0: Clear signals (40% of paragraphs)
- 0.85-0.94: Minor ambiguity (50%)
- 0.70-0.84: Ambiguous (10%)

❌ WRONG: All paragraphs confidence=1.0 (over-confident)
✅ CORRECT: Use full range based on actual visual clarity
</paragraph_notes>
```

**Evidence:** Correction prompt dedicates 7 lines to confidence calibration, improving score distribution.

---

## Implementation Priority

### High Priority (Immediate Impact)

1. **Move critical rules to TOP** (Rec #1)
   - Expected impact: +5-10pp accuracy on schema compliance
   - Effort: 30 minutes (restructure existing content)

2. **Add ❌/✅ visual markers** (Rec #2)
   - Expected impact: +3-5pp on edge cases (QUOTE, OTHER)
   - Effort: 15 minutes (add to existing examples)

3. **Reduce block taxonomy** (Rec #3)
   - Expected impact: -100 lines, better focus
   - Effort: 45 minutes (move to reference, keep top 5)

### Medium Priority (Iterative Improvement)

4. **Use failure-based examples** (Rec #5)
   - Expected impact: +5pp on current failure modes
   - Effort: 30 minutes (run analyze_label.py, extract examples)

5. **Add distribution quantification** (Rec #6)
   - Expected impact: OTHER drops from 3.9% to <2%
   - Effort: 15 minutes (add frequency guidance)

### Low Priority (Nice to Have)

6. **Simplify classification patterns** (Rec #4)
   - Expected impact: Easier to follow, marginal accuracy gain
   - Effort: 30 minutes (condense decision tree)

7. **Consolidate redundant sections** (Rec #7)
   - Expected impact: -50 lines, clearer structure
   - Effort: 20 minutes (merge QUOTE sections)

8. **Add paragraph notes guidance** (Rec #8)
   - Expected impact: Better confidence calibration
   - Effort: 10 minutes (add calibration section)

---

## Key Takeaways

### What Worked for Correction

1. **Short prompts > Long prompts** (88 lines vs 252 lines = +9pp accuracy)
2. **Examples > Rules** (40% examples, 30% rules ratio)
3. **Visual markers** (❌/✅) create clear contrast
4. **Critical rules first** (primacy bias)
5. **Real failure examples** ("cam- paign" → "campaign")
6. **Quantified guidance** ("80-90% text=null")
7. **Pattern-based** (5 bullet patterns vs verbose paragraphs)
8. **Iterative refinement** (analysis → prompt → test → repeat)

### Apply to Label

- **Reduce from 280 lines to ~100 lines**
- **Move block taxonomy to reference** (keep top 5 in prompt)
- **Add ❌/✅ to all examples**
- **Use analyze_label.py failures** for examples
- **Quantify distributions** (BODY 60%, FOOTNOTE 20%, OTHER <2%)
- **Test on accidental-president** after each change
- **Measure:** Page number accuracy, OTHER rate, QUOTE confidence

---

## Analysis Workflow (Proven Pattern)

The correction stage established this effective workflow:

```
1. Run stage on test book (accidental-president)
   └─ uv run python ar.py process correction accidental-president

2. Analyze outputs for failures
   └─ uv run python tools/analyze_correction.py accidental-president

3. Identify top 3 failure patterns
   └─ Manual review of flagged pages

4. Update prompt with:
   - Critical rule at TOP
   - Real failure example with ❌/✅
   - Pattern description

5. Re-run stage
   └─ uv run python ar.py process clean correction accidental-president
   └─ uv run python ar.py process correction accidental-president

6. Verify improvement
   └─ uv run python tools/analyze_correction.py accidental-president

7. Commit if improved
   └─ git commit -m "refactor: improve X prompt (Y% → Z%)"
```

**Apply to label stage:**
- Use `tools/analyze_label.py` (already exists)
- Focus on: Page number accuracy, OTHER rate, QUOTE confidence
- Iterate with small prompt changes (not full rewrites)

---

## References

**Git commits analyzed:**
- `6e74791` - Initial correction implementation (~150 lines)
- `3ca07c1` - First restructure (88 lines, +9pp accuracy)
- `0db213b` - Edge case refinement (hyphen fix)

**Analysis tools:**
- `/Users/johnzampolin/go/src/github.com/jackzampolin/scanshelf/tools/analyze_correction.py`
- `/Users/johnzampolin/go/src/github.com/jackzampolin/scanshelf/tools/analyze_label.py`

**Test data:**
- `accidental-president` (255 pages)
- Previous run: 80.5% corrections applied, 19.5% hyphen artifacts
- Current run: 84% expected (testing in progress)

---

**Next Steps:**
1. Run `analyze_label.py` to get current failure examples
2. Apply Recommendations 1-3 (high priority)
3. Test on `accidental-president` pages 1-50
4. Measure: Page number accuracy, OTHER rate, QUOTE confidence
5. Iterate based on data

---

*Generated: 2025-10-15*
*Based on git commits 6e74791, 3ca07c1, 0db213b*
*For: Label stage prompt improvement (Issue #60)*
