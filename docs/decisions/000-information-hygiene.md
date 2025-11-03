# 0. Information Hygiene (Context Clarity as First Principle)

**Date:** 2025-11-03

**Status:** Accepted (Foundational)

## Context

This codebase is designed for **AI-human pair programming**. Nearly every commit is co-authored with Claude. The structure optimizes for **rapid context acquisition** - for both AIs and humans arriving without prior knowledge.

## The Problem: Context Pollution

Large files with mixed concepts create noise:
- **For AIs:** Irrelevant patterns leak into context, suggesting wrong approaches
- **For humans:** Cognitive load increases, important details get missed
- **For both:** Hard to locate information, unclear boundaries

## Decision

**Optimize all codebase organization for context clarity.**

Every choice about structure, naming, comments answers: **"Does this make the codebase easier to understand quickly?"**

This principle informs ADR 001 (Think Data First), ADR 002 (Stage Independence), ADR 003 (Cost Tracking).

## The Practices

### Small Files, Clear Purpose

One concept per file. Easy to find > fewer total lines.

**Example:**
```
pipeline/ocr/schemas/
  ├── page_output.py    # One schema
  ├── metrics.py        # One schema
  └── report.py         # One schema
```

"Where's the OCR output schema?" → `ocr/schemas/page_output.py`

Trade-off: Slight duplication accepted for discoverability.

### Naming Conveys Meaning

Filenames teach before you open them.

```bash
$ ls docs/decisions/
000-information-hygiene.md      # Foundational principle
001-think-data-first.md         # Data-centric thinking
002-stage-independence.md       # Unix philosophy
```

**Conventions:**
- Stage names: `paragraph-correct` (hyphens)
- Schema files: `page_output.py` (concept_type)
- ADRs: `NNN-descriptive-name.md`

Avoid: `utils.py`, `misc/`, `pc_stage.py`

Test: Can you understand the file tree without opening files?

### Comments Only When Critical

Code explains WHAT, comments explain WHY (only when non-obvious).

**Current count:** ~10 comments in entire codebase (complex locking, stage headers, warnings).

**Why minimal:**
- Comments are noise in context window
- They lie when code changes
- Well-named code self-documents

**Good comment:**
```python
# Use gpt-4o-mini for 80% quality at 10% cost (see ADR 003)
model = "openai/gpt-4o-mini"
```

**Bad comment:**
```python
# Get the page number from the file
page_num = extract_page_number(filename)  # Obvious from code
```

**Alternatives:** Better naming, extract functions, ADRs for decisions, git commits for context.

### Clean Working Tree

Ideas in GitHub, history in git, working tree stays clean.

**Where things live:**
- Ideas/TODOs: GitHub issues
- History/context: Git commits
- Current state: Working tree (only active code)
- Decisions: ADRs

New contributors see only what IS, not what WAS or MIGHT BE.

**Avoid:**
```python
# TODO: Refactor later
# FIXME: This is broken
```

**Instead:** GitHub issue or fix it now.

Exception: Critical warnings (`# CRITICAL: Never call this without...`)

### Abstraction Boundaries

Clear units = clear understanding. One stage = one responsibility, one schema = one data contract, one file = one concept.

See ADR 002 (Stage Independence) for Unix philosophy application.

## Why This Matters: AI-Human Pair Programming

**The reality:** ~100% of commits co-authored with Claude. AI types, human judges. Fast iteration requires fast context acquisition.

**For AIs:**
- Large files = context pollution, wrong pattern suggestions
- Small files = relevant context, accurate patterns

**For humans:**
- Large files = cognitive overload, missed details
- Small files = manageable chunks, intuitive navigation

**The onboarding flow:**
1. Read `CLAUDE.md`
2. List file tree (structure teaches)
3. Read relevant files (small, focused)
4. Check ADRs (understand decisions)
5. Start working (productive in minutes)

**The goal:** New contributor (AI or human) feels "cozy and right inside their workshop, ready to do very productive work."

## How This Informs Other ADRs

- **ADR 001:** Files on disk = ground truth = transparent
- **ADR 002:** Clear boundaries = small composable units
- **ADR 003:** Separate MetricsManager = visible costs

## Consequences

**Enables:** Rapid onboarding, easy navigation, focused diffs, confident refactoring, productive collaboration.

**Requires:** Discipline to split files, thoughtful naming, resist comments, active cleanup, abstraction thinking.

## Alternatives Considered

- **Large files grouped by type** (`schemas.py`, `utils.py`): Hard to find, context pollution
- **Heavy documentation** (redundant docstrings): Adds noise, lies over time
- **TODO comments in code**: Stale, forgotten, noisy

All rejected: Discoverability and clarity matter more.

## Core Principle

**Context clarity is oxygen for productive collaboration.**

Clear context → Fast understanding → Confident changes → Productive iteration.

Everything else flows from this principle.
