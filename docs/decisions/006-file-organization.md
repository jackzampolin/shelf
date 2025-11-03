# 6. File Organization (Small Files, Clear Purpose)

**Date:** 2025-11-03

**Status:** Accepted

## Context

Organizing code into files: group by type (`schemas.py`, `utils.py`) or split by concept (one schema per file)? Choice affects discoverability and context clarity.

## Decision

**One concept per file. Easy to find > fewer total lines.**

**When to split:**
- Different schemas → different files
- Different stages → different directories
- Different concerns → different modules
- File growing past ~200 lines → likely doing too much

## Example: Schemas

```
pipeline/ocr/schemas/
  ├── page_output.py    # One schema
  ├── metrics.py        # One schema
  └── report.py         # One schema

NOT:
pipeline/ocr/
  └── schemas.py        # All schemas in one file
```

**Why this works:**
- Question: "Where's the OCR output schema?"
- Answer: `ocr/schemas/page_output.py`
- One grep result, not hunting through 300-line file

## When Starting New Code

**Ask:**
1. Does this concept exist elsewhere? (use existing file)
2. Is this a new concept? (create new file)
3. Would this file do multiple things? (split further)

**File size guideline:**
- Under 100 lines: Probably fine
- 100-200 lines: Check if it's doing one thing
- Over 200 lines: Likely needs splitting

**Exceptions:**
- Stage `__init__.py` can be 150-200 lines (orchestration)
- Complex prompts can be 200+ lines (single concept)
- Tools with many small functions can be 150-200 lines

## Trade-off Accepted

**Slight code duplication:** Common fields repeated across schemas.

**Worth it:** Discoverability > DRY.

Example: `page_num` and `scan_id` appear in multiple schemas. That's okay - each schema is independently understandable.

## Alternatives Considered

**Large files grouped by type** (`schemas.py`, `utils.py`):
- Problem: Hard to find specific schema
- Problem: Context pollution when reading
- Rejected: Discoverability matters more

**Aggressive DRY** (base classes for common fields):
- Problem: Harder to understand individual schemas
- Problem: Changes to base class ripple everywhere
- Rejected: Clarity > code reuse

## Core Principle

**Small files enable fast understanding.**

Finding the right file should take seconds, not minutes. Reading the file should fit in working memory.

Easy to find > fewer total lines.
