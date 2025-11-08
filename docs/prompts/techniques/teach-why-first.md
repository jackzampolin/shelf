# Teach WHAT/WHY Before HOW

**Principle:** Teach Generalization, Not Memorization

## The Problem

Instructions without context create mechanical following that can't handle variations.

```
❌ Instructions only:
1. Call list_boundaries()
2. Call grep_text()
3. Call get_page_ocr()
4. Return the result
```

**Model behavior:** Follows steps mechanically, confused by edge cases, can't adapt.

## The Solution

Start with philosophy (WHY the task matters), then principles (WHAT makes a good result), then instructions (HOW to do it).

```
✅ Philosophy → Principles → Examples → Instructions:

Philosophy: You're a detective finding truth through overlapping signals.
Principles: Each tool reveals something different, cross-verify for confidence.
Examples: When grep says X but boundaries say Y, what's the truth?
Instructions: 1. list_boundaries(), 2. grep_text()...
```

**Model behavior:** Understands context, handles edge cases, adapts flexibly.

## When to Use

- Complex tasks requiring judgment
- When strict rules won't cover all cases
- Tasks where understanding context matters
- Building agents that need to reason, not just execute

## How to Apply

**Structure: Philosophy → Principles → Examples → Instructions**

1. **Philosophy**: Why does this task matter? What's the goal?
   - Frame the problem
   - Explain the challenge
   - Describe the approach

2. **Principles**: What makes a good vs. bad result?
   - What to optimize for
   - What to avoid
   - How to think about edge cases

3. **Examples**: Show the philosophy in action
   - Demonstrate reasoning
   - Show judgment calls
   - Illustrate patterns

4. **Instructions**: Specific steps to follow
   - Tool usage
   - Workflow
   - Output format

## Codebase Example

`pipeline/link_toc/agent/prompts.py:5-20`

```python
<search_philosophy>
You have a ToC entry (a title) and need to find where that section begins in the book.

The challenge: OCR can have errors, boundaries might be mislabeled,
chapter numbers might be ambiguous.

Your advantage: Multiple overlapping signals that can confirm each other.

Think of it like detective work:
- LANDSCAPE: See the known boundaries (curated, clean, but might miss some)
- SEARCH: Look for your text across the whole book (noisy, but density reveals truth)
- INSPECT: Read actual text to verify candidates
- VISUAL: See the page when text alone isn't clear

Start targeted (boundaries), expand if needed (grep), always confirm (OCR),
use vision liberally (cheap, catches errors).
</search_philosophy>

# Then later: <tools_and_what_they_reveal>
# Then: <patterns_to_recognize>
# Finally: <reasoning_approach> and instructions
```

**Note:** Philosophy comes FIRST, before tool descriptions or instructions.

## Philosophy Section Elements

**Good philosophy sections include:**

1. **Task framing**: What are you trying to achieve?
2. **The challenge**: What makes this hard?
3. **Your advantage**: What helps you succeed?
4. **The approach**: How should you think about it?

**Example structure:**
```
<search_philosophy>
GOAL: Find where this ToC entry appears in the book

CHALLENGE: OCR errors, mislabeled boundaries, ambiguous matches

ADVANTAGE: Multiple signals that cross-verify

APPROACH: Think like a detective - gather evidence, cross-check, find truth
</search_philosophy>
```

## Why This Works

**Without philosophy (mechanical):**
- Model follows steps blindly
- Confused by edge cases (no context)
- Can't adapt (doesn't understand WHY)
- Brittle (breaks on variations)

**With philosophy (reasoning):**
- Model understands the goal
- Handles edge cases (has context for judgment)
- Adapts flexibly (knows WHY each step matters)
- Robust (generalizes to variations)

**Philosophy enables flexible reasoning over mechanical execution.**

## The Detective Metaphor

From `pipeline/link_toc/agent/prompts.py`:

```
Think of it like detective work:
- LANDSCAPE: See the known boundaries
- SEARCH: Look for your text across the book
- INSPECT: Read actual text to verify
- VISUAL: See the page when text fails
```

**Why this works:**
- Familiar mental model (detective)
- Explains tool relationships (different evidence types)
- Implies strategy (gather, cross-check, conclude)
- Enables judgment (detective makes decisions)

## Anti-Pattern

```
❌ Instructions without context:
"Use these tools:
1. list_boundaries() - Returns boundaries
2. grep_text() - Returns matches
3. get_page_ocr() - Returns text
4. view_page_image() - Returns image

Now search for the entry."

→ Model has no context for HOW to combine tools
→ Doesn't know WHEN to use vision vs. OCR
→ Can't handle conflicts (grep says X, boundaries say Y)
```

```
✅ Philosophy first, then tools:
"Philosophy: You're a detective using overlapping signals.

Tools reveal different aspects:
- Boundaries: Clean but incomplete (curated list)
- Grep: Noisy but complete (density reveals truth)
- OCR: Fast but error-prone (confirm findings)
- Vision: Accurate but expensive (final verification)

Strategy: Start targeted → Expand if needed → Always confirm"

→ Model understands tool relationships
→ Knows when to escalate (unclear → use grep → still unclear → use vision)
→ Handles conflicts (cross-verify, trust most reliable)
```

## Where to Put Philosophy

**Start of prompt:**
- Primacy effect (models pay attention to beginning)
- Sets context for everything that follows
- Frames the task before diving into details

**Tag it clearly:**
```
<philosophy>
<search_philosophy>
<approach>
<detection_philosophy>
```

Make it visually distinct, easy to find.

## Related Techniques

- `pattern-based-teaching.md` - Philosophy enables pattern recognition
- `multiple-signals.md` - Philosophy explains why multiple signals matter
- `xml-structure.md` - Use tags to make philosophy stand out
