# Cost Awareness

**Principle:** Economics-Aware Design

## The Problem

Without cost guidance, LLMs make expensive choices:
- Sequential page scanning: Load 500 images looking for ToC
- Redundant verification: Check same content multiple times
- Ignoring cheap alternatives: Vision instead of grep for text search

**Economics:** Grep is FREE. Vision is ~$0.001/image. 500 pages = $0.50 wasted.

## The Solution

Label operation costs explicitly. Guide the model to use cheap operations first, expensive only when necessary.

## When to Use

- Operations involving paid API calls (vision, LLM inference)
- Large search spaces (hundreds of pages to scan)
- Batch processing (cost multiplies across books)
- When cheap alternatives exist (grep vs. vision for text)

## How to Apply

1. **Label costs explicitly**:
   - `FREE` - Grep, file operations
   - `CHEAP (~$0.001)` - Vision API calls
   - `EXPENSIVE` - Large LLM context windows
2. **Provide cost-efficient strategy**: Cheap → Narrow → Expensive → Verify
3. **Set stopping conditions**: "STOP as soon as you're confident"
4. **Explain the economics**: Why this order? Why stop?

## Strategy Pattern

```
Cheap (target):    Grep for keywords → 3 candidate pages identified
↓
Expensive (verify): Load only those 3 images
↓
Stop (confident):   Found ToC on page 5, stop loading
```

**Cost:** ~$0.003 (3 images) instead of $0.50 (500 images)

## Codebase Example

`pipeline/find_toc/agent/prompts.py:32, 167-174`

```python
STEP 1: Get Grep Report (FREE - no cost)
→ Call get_frontmatter_grep_report()
→ Returns pages where keywords appear

STEP 2: Load images strategically based on grep hints
→ Only load candidate pages

<cost_awareness>
Vision model calls have real cost (grep is FREE).
- Strategy: Use grep to narrow candidates, then visually verify
- Grep-guided search significantly reduces total pages loaded
- STOP as soon as you're confident - don't over-verify
</cost_awareness>
```

**Note:** Explicit FREE/cost labels + stop condition.

## Economic Reasoning

At scale (see ADR 003):
- 100-page book: Unguided vision scan = $0.10, grep-guided = $0.003
- 100 books: $10 vs. $0.30 savings
- 1000 books: $100 vs. $3 savings

**Cost awareness isn't optimization, it's product viability.**

## Anti-Pattern

```
❌ No cost guidance:
"Search through the book to find the Table of Contents."

→ Model loads pages sequentially: 1, 2, 3, 4... 500
→ Cost: $0.50 per book
```

```
✅ Cost-aware strategy:
"1. Grep for ToC keywords (FREE)
 2. Load only candidate pages (minimal cost)
 3. Stop when found (don't over-verify)"

→ Model uses grep to identify pages 5-7, loads only those
→ Cost: $0.003 per book
```

## The Cost Ladder

**FREE operations:**
- Grep text search
- File existence checks
- Reading JSON/text files
- Status calculations

**CHEAP operations (~$0.001):**
- Single vision API call
- Small LLM inference
- OCR API call

**EXPENSIVE operations:**
- Large context windows (many images/pages)
- Redundant operations
- Unguided searches

**Guide the model up the ladder strategically, not wastefully.**

## Related Techniques

- `grep-guided-attention.md` - Cheap search guides expensive vision
- `multiple-signals.md` - Cross-verify to avoid redundant calls
