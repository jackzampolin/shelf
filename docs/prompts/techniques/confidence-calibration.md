# Confidence Calibration

**Principle:** Anticipate Failure Modes

## The Problem

Without rubrics, all results come back "high confidence" even when uncertain:

```
Result: boundary found, confidence: 0.95
Result: boundary found, confidence: 0.94
Result: boundary found, confidence: 0.97
```

**Reality:** Some were obvious (whitespace + fresh text), others ambiguous (mid-page, conflicting signals).

**Consequence:** Downstream stages can't filter low-quality results.

## The Solution

Provide explicit confidence ranges with concrete criteria.

```
High (0.9+):   Strong visual + textual alignment
Medium (0.7-0.9): One strong signal, other moderate
Low (<0.7):    Conflicting signals or ambiguous
```

**Result:** Model self-assesses accurately, downstream filtering works.

## When to Use

- Tasks with varying signal strength
- Ambiguous cases requiring judgment
- When downstream stages need quality filtering
- Quality control and error detection

## How to Apply

1. **Define thresholds**: High/Medium/Low with numeric ranges
2. **Provide concrete criteria**: "If you see X + Y → confidence = Z"
3. **Use examples**: Show what each level looks like
4. **Encourage honesty**: "Better to admit uncertainty than guess wrong"
5. **Explain tie-breaking**: "When in doubt, trust signal X over Y"

## Calibration Rubric

```
High confidence (0.9-1.0):
- Multiple strong signals align
- No conflicting evidence
- Clear, unambiguous case

Medium confidence (0.7-0.9):
- One strong signal, others moderate
- Minor conflicts or ambiguity
- Reasonable but not certain

Low confidence (0.5-0.7):
- Weak signals
- Conflicting evidence
- Best guess among bad options

Report "not found" (<0.5):
- No reasonable match
- Too ambiguous to call
```

## Codebase Example

`pipeline/label_pages/batch/prompts.py:137-152`

```python
<confidence_calibration>
**High confidence (0.9+):**
- Extensive whitespace + text starts fresh + top position
- OR minimal whitespace + starts mid-sentence + dense page

**Medium confidence (0.7-0.9):**
- Moderate whitespace + appears to continue (ambiguous)
- Mid-page position + fresh start (legitimate but less common)

**Low confidence (<0.7):**
- Visual says boundary, textual says continuation (likely running header)
- Conflicting signals requiring judgment call
- Very ambiguous layout

**When in doubt, trust the textual flow over visual prominence.**
</confidence_calibration>
```

**Note:** Specific criteria + tie-breaking rule.

Also: `pipeline/link_toc/agent/prompts.py:113-133` has detailed confidence criteria.

## Tie-Breaking Rules

When signals conflict, provide explicit guidance:

```
"When in doubt, trust textual flow over visual prominence."
"OCR errors are common in Roman numerals - use vision for final verification."
"Grep density trumps single boundary match."
```

**Result:** Model makes consistent decisions under uncertainty.

## Why This Works

**Calibrated confidence enables:**
1. **Downstream filtering**: Drop results < threshold
2. **Quality metrics**: Track calibration accuracy
3. **Error detection**: Flag low-confidence for review
4. **Honest uncertainty**: Model admits "I don't know"

**Uncalibrated confidence:**
- Everything is 0.95
- Can't filter quality
- Can't detect errors
- False certainty

## Anti-Pattern

```
❌ Vague confidence instruction:
"Return a confidence score between 0 and 1."

→ Model returns 0.95 for everything, no useful signal
```

```
✅ Calibrated rubric:
"High (0.9+): Extensive whitespace + text starts fresh
 Medium (0.7-0.9): Moderate whitespace + ambiguous flow
 Low (<0.7): Conflicting signals"

→ Model self-assesses accurately, useful filtering
```

## Testing Calibration

Review results:
- Do high-confidence results (0.9+) have high accuracy?
- Do low-confidence results (<0.7) have low accuracy?
- If calibration is off, adjust thresholds or criteria

**Goal:** Confidence scores predict accuracy.

## Related Techniques

- `failure-modes.md` - Named pitfalls help calibration
- `multiple-signals.md` - Cross-verification increases confidence
