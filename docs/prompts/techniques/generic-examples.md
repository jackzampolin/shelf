# Generic Examples Instead of Actual Data

**Principle:** Teach Generalization, Not Memorization

## The Problem

Using actual content from test books teaches the model to recognize THAT BOOK, not the pattern.

```
❌ Example: "Part I: April 12, 1945" followed by "The First Days ... 15"
```

Model learns: "Look for April 12, 1945" → Overfitting → Fails on other books

## The Solution

Use made-up content that demonstrates the abstract pattern.

```
✅ Example: "Part I: The Ancient World" followed by "Chapter 1: Early Civilizations ... 1"
```

Model learns: "Parent entry (no page #) followed by indented children (with page #s)" → Generalizes

## When to Use

- Teaching structural patterns (ToC formats, hierarchies, layouts)
- Providing examples of "what it looks like"
- Any time you show the model an example

## How to Apply

1. **Identify the abstract pattern**: What structure are you teaching?
2. **Strip out specific content**: Remove book-specific text
3. **Replace with generic placeholders**:
   - Temporal: "Ancient World", "Medieval Period", "Modern Era"
   - Sequential: "Early Days", "Middle Period", "Late Phase"
   - Neutral: "Topic A", "Subtopic 1", "Section i"
4. **Add explicit comment**: "# These are GENERIC patterns (NOT from any specific book)"

## Codebase Example

`pipeline/extract_toc/detection/prompts.py:161-205`

```python
<generic_pattern_examples>
# These are GENERIC patterns to teach structure recognition (NOT from any specific book)

Pattern 2: Two-level hierarchy
```
The Beginning .......................... 1
  Background ........................... 3
  Context .............................. 12
The Middle ............................. 25
  Developments ......................... 27
```
```

**Note:** Explicit comment prevents accidental overfitting.

## The Test

Ask yourself: **"Would this example work for ANY book, or just the one I'm testing?"**

If it only works for your test book → overfitting → rewrite with generic content.

## Anti-Pattern

```
# Using chapter 3 as example because it shows the pattern well
Example: "Chapter III: The War Begins on April 6, 1917"
```

Problems:
- Specific date ties to one book
- "War Begins" is book content, not structure
- Model might look for dates or war-related text

## Related Techniques

- `pattern-based-teaching.md` - Teach visual signs, not content
- `teach-why-first.md` - Philosophy before examples
