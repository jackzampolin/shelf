# XML Structure for Prompts

**Principle:** Information Hygiene

## The Problem

Long unstructured prompts create context pollution:

```
You are a ToC finder. You should look for pages with ToC keywords.
Then verify visually. The output should include toc_found and confidence.
Also document the structure. Use grep first because it's free. Vision
costs money. If you see running headers don't confuse them with boundaries.
The format is JSON with these fields...
```

**Result:** Signal lost in noise, critical instructions buried, model skims.

## The Solution

Use semantic XML tags to create clear structure. LLMs process sequentially - structure guides attention.

```
<role>You are a ToC finder.</role>

<cost_awareness>
Use grep first (FREE), then vision (costs money).
</cost_awareness>

<critical_instructions>
Don't confuse running headers with boundaries.
</critical_instructions>

<output_requirements>
Format: JSON with toc_found, confidence, structure.
</output_requirements>
```

**Result:** Clear sections, critical info stands out, model follows precisely.

## When to Use

- Prompts > 500 words (long enough to need structure)
- Multiple distinct sections (role, task, examples, output)
- Critical instructions (must be followed precisely)
- Complex workflows (multiple steps with context)

## How to Apply

1. **Use semantic tags**: Name reflects content
   - `<role>` - Who the model is
   - `<task>` - What to do
   - `<critical_instructions>` - Must-follow rules
   - `<output_requirements>` - Format expectations
2. **Put critical info at START and END**: Primacy/recency effects
3. **Group related concepts**: Keep sections focused
4. **Don't overuse**: Simple prompts don't need tags

## Tag Vocabulary

**Common tags from codebase:**
- `<role>` - Agent identity/capabilities
- `<task>` / `<goal>` - Objective
- `<philosophy>` / `<approach>` - Underlying reasoning
- `<critical_instructions>` - Must-follow rules
- `<tool_workflow>` - Multi-step process
- `<output_requirements>` - Format/schema
- `<examples>` - Demonstrations
- `<cost_awareness>` - Economic guidance
- `<failure_modes>` / `<common_false_positives>` - Pitfalls

**Keep tag names descriptive and consistent across prompts.**

## Primacy/Recency

LLMs pay more attention to:
- **START** of context (primacy effect)
- **END** of context (recency effect)

Structure accordingly:
```
<role> + <critical_instructions>   ← START (primacy)
<task> + <philosophy>
<examples> + <tool_workflow>
<output_requirements>              ← END (recency)
```

Critical rules at top, output format at bottom.

## Codebase Example

`pipeline/find_toc/agent/prompts.py:1-5, 167-264`

```python
SYSTEM_PROMPT = """<role>
You are a Table of Contents finder with vision capabilities.
</role>

<detection_philosophy>
DETECT ToC BY COMBINING TEXT HINTS + VISUAL STRUCTURE.
</detection_philosophy>

<tool_workflow>
STEP 1: Get Grep Report (FREE)
STEP 2: Load images strategically
STEP 3: Synthesize structure
STEP 4: Write result
</tool_workflow>

<cost_awareness>
Vision costs money. Use grep to narrow candidates first.
</cost_awareness>

<output_requirements>
Call write_toc_result() with:
- toc_found, toc_page_range, confidence, structure_summary
</output_requirements>
"""
```

**Note:** Clear sections, critical info at START/END, scannable.

## When NOT to Use

`pipeline/extract_toc/assembly/prompts.py` - Simple, short prompt (~50 lines):

```python
SYSTEM_PROMPT = """You are a Table of Contents assembly specialist.

Your task is to merge ToC entries from multiple pages into a final structure.

DO NOT re-interpret hierarchy—trust Phase 1's extraction."""
```

**No tags needed.** Simple prompts stay simple. Don't over-engineer.

## Anti-Pattern

```
❌ Wall of text (no structure):
Long paragraph mixing role, instructions, examples, output format,
warnings, edge cases, cost notes, all in 500 words with no breaks...

→ Context pollution, critical info buried, model skims
```

```
✅ Structured with tags:
<role>...</role>
<critical_instructions>...</critical_instructions>
<task>...</task>
<output_requirements>...</output_requirements>

→ Clear sections, easy to scan, model follows
```

## Related Techniques

- `trust-upstream.md` - Clear scope boundaries in prompts
- `teach-why-first.md` - Philosophy section benefits from tagging
