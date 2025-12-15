# 8. Cordon Sanitaire (Temporal Boundaries)

**Date:** 2025-12-15

**Status:** Accepted

## Context

Information hygiene (ADR 000) requires more than cleanliness—it requires **enforced boundaries**. Information isn't dirty in itself; it becomes contaminating when it crosses into the wrong zone.

The term *cordon sanitaire* names this: a quarantine line where crossing is the problem, not the material on either side.

## Decision

**Three temporal zones. No leakage into the working tree.**

| Zone | Contains | Lives in |
|------|----------|----------|
| **Past** | How we got here | Git history, closed issues/PRs |
| **Present** | What the code does now | Working tree (main/go-rewrite) |
| **Future** | What we might do next | GitHub issues/projects |

**The working tree is present tense only.**

## Why Boundaries, Not Just Organization

When an agent (AI or human) loads context, material from the wrong zone degrades focus:
- Future speculation suggests patterns that don't exist yet
- Commented-out past implies the code is provisional
- Mixed temporality creates uncertainty about what's real

The cordon isn't about tidiness. It's about **protecting the epistemic integrity of the codebase**.

## Enforcement

**Past stays in git/GitHub:**
- No commented-out code "for reference"
- No comments explaining what code used to do
- History lives in `git log` and closed issues/PRs

**Future stays in GitHub:**
- `// TODO` → Create an issue, delete the comment
- `// FIXME` → Create an issue or fix it now
- `// HACK` → ADR explaining necessity, or refactor
- No `PLAN.md`, `docs/research/`, or speculative documentation in the repo
- Plans, research, and proposals live in GitHub issues/discussions

**Present stays in working tree:**
- Active, working code
- Comments explaining non-obvious WHY (present tense)
- Safety warnings (see exception below)

## Exception: Safety Warnings

Inline safety warnings are present-tense information about current behavior. They stay:
```go
// WARNING: This operation cannot be undone
// CRITICAL: Must be called with lock held
```

```python
# CRITICAL: This endpoint costs $0.02 per call
# WARNING: Rate limit is 60/min
```

## Consequences

**Enables:** Clear context, confident agents, focused diffs, unambiguous present.

**Requires:** Discipline to relocate information to its temporal home.

## Core Principle

**The information isn't dangerous. Its presence in the wrong zone is.**
