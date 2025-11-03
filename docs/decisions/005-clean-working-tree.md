# 5. Clean Working Tree (Ideas in GitHub, Not Code)

**Date:** 2025-11-03

**Status:** Accepted

## Context

Code files can become cluttered with future intentions: TODO comments, FIXME notes, planning comments. These create noise in the context window and working tree.

## Decision

**Working tree contains only current, active code. Ideas and planning live elsewhere.**

**Where things live:**
- **Ideas/TODOs:** GitHub issues
- **Planning:** GitHub issues with milestones
- **Long-term vision:** GitHub issues labeled "enhancement"
- **History/context:** Git commit messages
- **Current state:** Working tree (only active code)
- **Decisions:** ADRs in `docs/decisions/`

## Why This Matters

When new contributor checks out repo:
```bash
$ git status
On branch main
nothing to commit, working tree clean
```

They see only what IS, not what WAS (git log) or MIGHT BE (issues).

## Anti-Patterns to Avoid

```python
# TODO: Refactor this later
# FIXME: This is broken
# HACK: Temporary workaround
# NOTE: Remember to update X when Y changes
```

**Instead:**
- TODO → Create GitHub issue, reference in commit if urgent
- FIXME → GitHub issue or fix it now
- HACK → Refactor it or document in ADR why temporary
- NOTE → Git commit message or ADR if decision-worthy

## Exception

Critical warnings about footguns:
```python
# CRITICAL: Never call this without checking status first
# WARNING: This operation cannot be undone
```

These stay - they prevent immediate harm.

## Planning in GitHub

**Short-term work:** GitHub issues with clear acceptance criteria
**Long-term vision:** GitHub issues labeled "enhancement" or "research"
**Milestones:** Group related issues, track progress

Benefits:
- Searchable (grep through issues, not code)
- Trackable (can close, reference, link)
- Discussable (comments, not commit messages)
- Prioritizable (labels, milestones)

## Consequences

**Enables:** Clean context for new sessions, grep finds code not TODOs, clear separation of current vs. future.

**Requires:** Discipline to create issues instead of TODO comments, active issue management.

## Core Principle

**The working tree is reality. Everything else is history (git) or possibility (GitHub).**

Clean tree = clear mind = productive work.
