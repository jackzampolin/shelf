# Trust Upstream Stages

**Principle:** Information Hygiene

## The Problem

Downstream stages second-guessing upstream work creates inconsistency.

```
Phase 1 (extraction): "Entry is Level 2 (indented, sub-entry)"
Phase 2 (assembly): "This looks like Level 1 to me, I'll change it"
```

**Result:**
- Inconsistent hierarchy across stages
- Undermines pipeline design
- Creates confusion (which stage is right?)
- Wastes effort (re-doing upstream work)

## The Solution

Define clear scope boundaries. Downstream stages trust upstream decisions unless obviously wrong.

```
Phase 1: Extract entries with hierarchy levels (owns this decision)
Phase 2: Assemble entries, merge continuations (does NOT re-interpret levels)
```

**Result:** Each stage has clear responsibility, no overlap, consistent output.

## When to Use

- Multi-stage pipelines with dependencies
- When later stages process output from earlier stages
- Assembly or aggregation tasks
- Any time you're tempted to "fix" upstream results

## How to Apply

1. **Explicitly state**: "DO NOT re-interpret upstream decisions"
2. **Define boundaries**: What this stage does vs. doesn't do
3. **Trust by default**: Only flag obvious errors, don't fix
4. **Preserve upstream format**: Don't reformat unless necessary
5. **Document scope**: "Your job is X, NOT Y"

## Scope Boundary Pattern

```
✅ Clear scope:
"Your job: Merge continuation entries across pages
 NOT your job: Re-check hierarchy levels (trust Phase 1)
 NOT your job: Fix capitalization (preserve as-is)
 NOT your job: Infer missing page numbers (preserve null)"
```

## Codebase Example

`pipeline/extract_toc/assembly/prompts.py:13, 93-97`

```python
DO NOT re-interpret hierarchy or structure—trust Phase 1's extraction.

# Later in the prompt:
**TRUST PHASE 1**:
DO NOT change hierarchy levels. If Phase 1 said an entry is Level 2, keep it Level 2.
DO NOT re-capitalize or reformat titles beyond merging continuations.
DO NOT infer missing page numbers—preserve exactly as extracted.
```

**Note:** Explicit "DO NOT" statements + scope definition.

## What This Enables

**Pipeline independence** (from ADR 002):
- Each stage owns specific decisions
- Clear interfaces (files on disk)
- Testable in isolation
- Debuggable (inspect each stage's output)

**Consistent output:**
- Phase 1 decides hierarchy → Phase 2 preserves it
- No conflicts between stages
- Single source of truth per decision

**Efficient iteration:**
- Change hierarchy logic → Only update Phase 1
- Don't need to touch Phase 2 (it trusts Phase 1)
- Easier refactoring

## When NOT to Trust

**Flag obvious errors, don't fix silently:**

```
# In assembly stage
if entry has no title:
    validation_issues.append("Entry #{num} missing title")
    # But still include it in output, let upstream fix

# Don't:
if entry has no title:
    entry.title = "Unknown"  # Silently fixing upstream issue
```

**Preserve errors, report them, let upstream stage handle fixes.**

## The Boundary Rule

**Each stage has clear boundaries:**

```
Stage A owns: OCR text extraction
Stage B owns: Boundary detection
Stage C owns: ToC entry extraction
Stage D owns: Entry assembly
```

**Downstream stages:**
- Use upstream output (read files)
- Don't re-interpret upstream decisions
- Report issues, don't fix silently
- Preserve upstream format

## Anti-Pattern

```
❌ Downstream re-interpretation:
"Assemble the ToC from Phase 1 entries.
 Also re-check the hierarchy levels and fix any errors you see.
 If capitalization looks wrong, fix it.
 Infer missing page numbers if you can."

→ Undermines Phase 1
→ Creates inconsistency (which stage is right?)
→ Duplicates effort
→ Makes bugs hard to track (which stage caused the issue?)
```

```
✅ Clear scope boundaries:
"Assemble the ToC from Phase 1 entries.
 Merge continuations across pages.

 DO NOT change hierarchy levels (trust Phase 1).
 DO NOT fix capitalization (preserve as-is).
 DO NOT infer missing data (preserve nulls)."

→ Respects Phase 1 decisions
→ Consistent output
→ Clear responsibilities
→ Easy to debug (each stage owns specific decisions)
```

## Maps to ADR 002

**Stage Independence** (ADR 002):
- Stages communicate through files
- No imports of processing logic
- Each stage owns its domain
- Clear interfaces

**Trust Upstream** is the prompt-level implementation:
- Don't second-guess upstream decisions
- Clear scope boundaries
- Preserve upstream format
- Report issues, don't fix

## Validation vs. Re-interpretation

**Validation (OK):**
```
# Check for obvious errors, report them
if entry.level not in [1, 2, 3]:
    validation_issues.append(f"Invalid level: {entry.level}")

# But preserve the value, don't "fix" it
output.append(entry)  # Include as-is
```

**Re-interpretation (NOT OK):**
```
# Silently changing upstream decisions
if entry.level == 2 and looks_like_level_1(entry):
    entry.level = 1  # ❌ Second-guessing Phase 1
```

## Related Techniques

- `xml-structure.md` - Use tags to make scope boundaries clear
- ADR 002 (Stage Independence) - Architectural foundation
