# Named Failure Modes

**Principle:** Anticipate Failure Modes

## The Problem

Generic warnings don't prevent errors:

```
❌ "Be careful about false positives."
```

**Model behavior:** Ignores warning, repeats same mistakes.

**Example error:** Confuses running headers with chapter boundaries (happens repeatedly).

## The Solution

Name each failure pattern explicitly. Describe visual/textual signs. Provide detection logic.

```
✅ **RUNNING HEADERS - These are NOT boundaries:**

Signs:
- Text at very top of page (header margin)
- Page appears DENSE with content
- OCR shows text continuing mid-paragraph

If you see these signs → CONTINUATION PAGE, not boundary
```

**Model behavior:** Recognizes pattern, applies explicit logic, avoids error.

## When to Use

- Tasks with common false positives
- Ambiguous visual patterns (running headers, continued entries)
- When you've observed repeated errors in testing
- Domain-specific edge cases

## How to Apply

1. **Observe errors**: What mistakes does the model make?
2. **Name the pattern**: Give it a clear, descriptive name
3. **Describe detection signs**: What visual/textual cues reveal this pattern?
4. **Provide explicit branch logic**: "If X → Do Y"
5. **Give concrete examples**: Show the pattern in action

## Failure Mode Template

```markdown
**[PATTERN NAME] - [What NOT to mistake it for]:**

[Brief description of the pattern]

Signs:
- Visual sign 1
- Textual sign 2
- Context sign 3

If you see these signs → [Correct classification]

[Optional: Reasoning why this is tricky]
```

## Codebase Example

`pipeline/label_pages/batch/prompts.py:74-98`

```python
<common_false_positives>
**RUNNING HEADERS - These are NOT boundaries:**

Running headers are chapter/section titles repeated at the top of EVERY page in a section.

Signs of a running header:
- Text appears at very top of page (in header margin)
- Small or same size as body text (not prominently large)
- Body text starts immediately below with minimal spacing
- Page appears DENSE with content
- OCR shows text continuing mid-paragraph

**If you see these signs, it's a CONTINUATION PAGE, not a boundary.**

Visual heading prominence is MISLEADING here - trust the textual flow.

**MID-PAGE SECTION HEADINGS:**

Pages can have section headings in the middle but still be continuation pages if:
- Page STARTS with body text (top of page)
- Heading appears LATER in the flow
- Text before heading continues from previous page

Mark position as "middle" but be LESS confident if text continues at top.
</common_false_positives>
```

**Note:** Two named patterns + explicit detection signs + decision logic.

## Multiple Named Patterns

`pipeline/link_toc/agent/prompts.py:56-86` names 5 specific patterns:

```python
<patterns_to_recognize>
**Density Pattern (running headers)**
Grep returns match counts per page. Look for:
- Sparse matches (1-2 per page): Scattered mentions
- Dense cluster (3-5 per page): Chapter extent
- First page of dense cluster: Chapter boundary

**Sequence Pattern (gap reasoning)**
Boundaries show: Chapter XII → ??? → Chapter XIV
The gap is likely Chapter XIII (between neighbors)
Verify with OCR or vision

**OCR Error Pattern**
"Chapter VIII" OCR'd as "Chapter Vil" or "Chapter VIll"
Roman numerals especially error-prone
Solution: Use sequence reasoning + visual verification

**Ambiguous Match Pattern**
Multiple pages have "Part II" in heading preview
Which is the actual boundary?
Grep shows density (running headers reveal true extent)

**Not Found Pattern**
No boundary matches, grep returns nothing or sparse matches
Entry might be:
- Mislabeled in ToC (wrong title)
- Not a boundary (subsection within chapter)
- Missing from book (ToC error)
Report honestly with lower confidence
</patterns_to_recognize>
```

**Note:** 5 named patterns, each with detection logic and handling.

## Why Naming Matters

**Generic warning (weak):**
```
"Watch out for running headers"
→ No definition, no detection logic, model ignores
```

**Named pattern (strong):**
```
**RUNNING HEADERS - NOT boundaries:**
Signs: Top of page + dense content + text continues mid-paragraph
If these signs → CONTINUATION PAGE
```
→ Clear definition, explicit logic, model applies

**Naming creates:**
- **Recognition** - "I've seen this pattern before"
- **Detection logic** - "Here's how to spot it"
- **Action** - "Here's what to do when you see it"

## Detection Signs Format

**Visual signs:**
- What you see in the image
- Spatial layout, styling, density

**Textual signs:**
- What the OCR text shows
- Flow, continuity, sentence structure

**Context signs:**
- Where in the book (front matter, body, appendix)
- Surrounding content

**Combine all three for reliable detection.**

## Branch Logic

**If-Then pattern:**
```
If [signs A, B, C present] → [Classification/Action]
```

**Examples:**
```
If text at top + dense page + continues mid-sentence → CONTINUATION PAGE
If extensive whitespace + fresh text start → BOUNDARY PAGE
If grep dense cluster + first page of cluster → CHAPTER START
```

**Make logic explicit, testable, falsifiable.**

## Why This Works

**Models need explicit guidance:**
- Generic warnings don't prevent errors
- Named patterns create recognition
- Detection logic enables consistent application

**Learning from errors:**
- Observe what mistakes happen
- Name the pattern
- Add to failure modes section
- Model stops making that mistake

**Accumulating knowledge:**
- Each refinement adds a pattern
- Patterns compound (cover more edge cases)
- Prompts get better over iterations

## Anti-Pattern

```
❌ Generic warning:
"Be careful about false positives. Some pages might look like boundaries but aren't."

→ Vague, no guidance, model ignores
```

```
✅ Named failure mode:
"**RUNNING HEADERS - NOT boundaries:**
Signs: Text at top + dense page + text continues mid-paragraph
If you see these → CONTINUATION PAGE

Trust textual flow over visual prominence."

→ Named, explicit detection, actionable
```

## Testing Failure Modes

**Review results:**
1. Does the model still make this error?
2. Are the detection signs correct?
3. Is the logic clear enough?

**If errors persist:**
- Add more specific detection signs
- Strengthen the language ("NEVER mistake X for Y")
- Provide more examples

**Goal:** Zero occurrences of the named failure mode.

## Related Techniques

- `confidence-calibration.md` - Use failure mode detection to adjust confidence
- `pattern-based-teaching.md` - Named patterns teach recognition
- `multiple-signals.md` - Use signals to cross-verify and avoid pitfalls
