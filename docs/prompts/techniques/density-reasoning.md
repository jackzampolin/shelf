# Density-Based Reasoning

**Principle:** Triangulate Truth from Multiple Sources

## The Problem

Raw grep results are noisy:
- "Chapter XIII" appears on page 5 (previous chapter mentions it)
- "Chapter XIII" appears on page 45 (actual chapter start)
- "Chapter XIII" appears on pages 45-62 (running headers throughout)
- "Chapter XIII" appears on page 63 (next chapter references it)

Which page is the actual boundary? Binary presence/absence can't tell you.

## The Insight

**Running headers create density patterns.**

Books put chapter titles in page headers. A chapter spanning pages 45-62 shows that title on EVERY page. Result: Dense clusters reveal chapter extent, first page = boundary.

## When to Use

- Analyzing grep search results (match counts per page)
- Finding chapter/section boundaries
- Distinguishing running headers from scattered mentions
- Identifying section extent (start and end)

## How to Apply

1. **Grep returns frequency, not just presence**: `{scan_page, match_count, context}`
2. **Identify density patterns**:
   - **Sparse** (1-2 matches/page): Scattered mentions, cross-references
   - **Dense cluster** (3-5+ matches/page): Running headers throughout section
3. **First page of dense cluster = boundary**: Where section starts
4. **Explain the mechanism**: Teach the model WHY density matters
5. **Use density to cross-check** other signals (boundaries, OCR)

## Pattern Recognition

```
Page 44:    1 match   → Previous chapter mentions next
Page 45:    5 matches → BOUNDARY (chapter starts + running headers begin)
Pages 46-62: 3-4 matches each → Running headers throughout chapter
Page 63:    1 match   → Next chapter references previous
```

**Conclusion:** Chapter XIII starts at page 45, runs through page 62.

## Codebase Example

`pipeline/link_toc/agent/prompts.py:30-41, 56-66`

```python
**grep_text(query)**
Key insight: Running headers create DENSITY
- Books put chapter titles in page headers
- A chapter spanning pages 45-62 will show that title on EVERY page
- Result: Dense clusters reveal chapter extent, first page = boundary

**Density Pattern (running headers)**
grep_text returns match counts per page. Look for:
- Sparse matches (1-2 per page): Scattered mentions
- Dense cluster (3-5 per page): Chapter extent
- First page of dense cluster: Chapter boundary
```

## Why This Works

**Book structure creates the signal:**
- Running headers repeat the chapter title on every page within that chapter
- This creates a contiguous region of high match density
- Density boundaries align with chapter boundaries
- Scattered mentions (previews/references) show low density

**The pattern is structural, not semantic.**

## Anti-Pattern

```
❌ Binary grep: "Chapter XIII found on pages 5, 45, 46, 47..., 63"
→ Can't distinguish boundary from mentions
```

```
✅ Density-based: "Pages 45-62 show 3-5 matches each (dense cluster)"
→ Reveals chapter extent and boundary
```

## Related Techniques

- `grep-guided-attention.md` - Use grep to guide vision
- `multiple-signals.md` - Cross-verify with boundaries, OCR, vision
- `cost-awareness.md` - Grep is free, use it strategically
