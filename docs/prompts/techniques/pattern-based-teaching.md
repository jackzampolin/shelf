# Pattern-Based Teaching (Not Rules)

**Principle:** Teach Generalization, Not Memorization

## The Problem

Rigid format enumeration breaks on variation:

```
❌ ToC must be one of these formats:
1. "Contents" heading with roman numeral pages
2. "Table of Contents" heading with arabic pages
3. "List of Chapters" with decimal numbering
...
[20 more specific formats]
```

**Result:** Format #21 arrives (graphical heading, mixed numbering) → fails.

## The Solution

Teach **what to look for** (visual signs, structural properties) instead of **what it must be** (rigid formats).

```
✅ ToC visual patterns:
- Vertical list structure (entries stacked)
- Right-aligned numbers (page references)
- Hierarchical indentation (parent/child)
- May have various headings: "Contents", "Table of Contents", graphical/stylized
```

**Result:** Model recognizes the pattern, adapts to variations.

## When to Use

- Complex, variable formats (ToC layouts, document structures)
- When you can't enumerate all possible cases
- Teaching recognition rather than classification
- Domains with natural variation (books, handwriting, forms)

## How to Apply

1. **Identify visual signs**: What do you SEE? (indentation, alignment, spacing)
2. **Describe structural properties**: How is it organized? (hierarchy, flow, density)
3. **Provide multiple examples**: Show variations of the pattern
4. **Explain the WHY**: Why does this pattern exist? (running headers, visual hierarchy)
5. **Avoid exhaustive enumeration**: Don't list all formats

## Pattern vs. Rule

**Rule-based (brittle):**
```
ToC heading must be:
- "Table of Contents" OR
- "Contents" OR
- "List of Chapters"

If heading doesn't match → NOT a ToC
```

**Pattern-based (flexible):**
```
ToC visual markers:
- Heading at top (text may vary: "Contents", "ORDER OF BATTLE", graphical)
- Vertical list structure below
- Right-aligned page numbers
- Hierarchical indentation visible

Look for the PATTERN, not specific text.
```

## Codebase Example

`pipeline/find_toc/agent/prompts.py:14-27`

```python
TOC VISUAL MARKERS (what you see in images):
- Vertical list of entries (many lines forming a list structure)
- Right-aligned column of numbers (page references)
- Leader dots or whitespace connecting titles to numbers
- Hierarchical indentation (parent/child relationships visible)
- May have non-standard titles: "ORDER OF BATTLE", "LIST OF CHAPTERS", graphical/stylized "CONTENTS"

NOT A TOC:
- Dense paragraph text
- No page number column
- Single chapter title (body page start)
```

**Note:** Teaches WHAT TO SEE (visual patterns) not formats.

## Why This Works

**Books are variable:**
- Different eras, different styles
- Non-standard headings ("ORDER OF BATTLE", graphical titles)
- Mixed numbering schemes
- Unusual hierarchies

**Patterns are universal:**
- Lists have vertical structure
- Page references align right
- Hierarchy shows through indentation

**Teaching patterns → generalization across variations.**

## Anti-Pattern

```
❌ Exhaustive enumeration:
"If heading is 'Contents' and uses roman numerals → Type A ToC
 If heading is 'Table of Contents' and uses arabic → Type B ToC
 If heading is 'List of Chapters' and uses decimal → Type C ToC
 ..."

→ Brittle, breaks on Type D (graphical heading + mixed numbering)
```

```
✅ Pattern recognition:
"Look for: vertical list + right-aligned numbers + hierarchical indentation
 Heading text can vary (Contents, ToC, ORDER OF BATTLE, graphical)
 Numbering can vary (roman, arabic, decimal, mixed)"

→ Flexible, recognizes new variations
```

## Related Techniques

- `generic-examples.md` - Use generic content to teach patterns
- `teach-why-first.md` - Philosophy enables pattern recognition
- `failure-modes.md` - Named patterns for common pitfalls
