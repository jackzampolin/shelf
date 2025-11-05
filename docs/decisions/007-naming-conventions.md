# 7. Naming Conventions (Consistency Prevents Bugs)

**Date:** 2025-11-03

**Status:** Accepted

## Context

Inconsistent naming caused real bugs: `paragraph_correct` vs `paragraph-correct` caused lookup failures between CLI/storage/logs. Naming is not cosmetic - it's a source of truth.

## Decision

**Establish consistent naming patterns across the codebase.**

## Stage Names

**Format:** `lowercase-with-hyphens`

**Examples:**
- `tesseract` (single word, no hyphen needed)
- `ocr-pages`
- `label-pages`
- `find-toc`
- `extract-toc`

**Why hyphens:** Consistency across CLI args, directory names, file references, log paths.

**Why this matters:** Inconsistency between stage names (hyphens vs underscores) causes lookup failures between CLI, storage, and logs.

## Schema Files

**Format:** `concept_type.py`

**Examples:**
- `page_output.py` (what it represents + its nature)
- `metrics.py` (simple concept, no compound needed)
- `report.py`

**Avoid:** Generic names like `schema.py`, `data.py`

## Architecture Decision Records

**Format:** `NNN-descriptive-kebab-case.md`

**Examples:**
- `000-information-hygiene.md`
- `001-think-data-first.md`
- `002-stage-independence.md`

**Why:** Number indicates order/hierarchy, descriptive name teaches before opening.

## Directories

**Format:** Hierarchy shows relationships

```
pipeline/tesseract/
  ├── schemas/          # Group by function
  ├── tools/            # Group by function
  └── __init__.py       # Stage entry point
```

**Avoid:** Flat structure, generic names (`misc/`, `stuff/`)

## General Guidelines

**Files:** `lowercase_with_underscores.py`, descriptive (`page_processor.py` not `proc.py`)
**Classes:** `PascalCase`, descriptive (`LabelPagesStage` not `LPStage`)
**Functions:** `snake_case`, verb-first (`process_page`, `get_status`)
**Constants:** `UPPER_SNAKE_CASE` for true constants only

## The Test

**Can someone understand the file tree organization without opening any files?**

```bash
$ ls docs/decisions/
000-information-hygiene.md      # Foundational
001-think-data-first.md         # Data philosophy
002-stage-independence.md       # Unix philosophy
```

Before reading content, you know:
- 000 is foundational
- 001 is about data
- 002 is about independence

**That's good naming.**

## Avoid

**ALL_CAPS_FILES.md** (shouting), **generic.py** / **utils.py** (junk drawers), **tmp_something.py** (belongs in .gitignore), **module1.py** (numbers aren't names)

## Core Principle

**Filenames teach before you open them.**

Good naming frontloads understanding. Bad naming creates mystery.

Consistency prevents bugs. The hyphen/underscore bug taught us this.
