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

This principle informs ADR 001 (Cordon Sanitaire), ADR 002 (Cost Tracking), ADR 005 (DefraDB Source of Truth).

## The Practices

This principle manifests in specific practices (each documented in detail):

- **ADR 001: Cordon Sanitaire** - Ideas in GitHub, not TODO comments
- **ADR 003: File Organization** - Small files, clear purpose (one concept per file)
- **ADR 004: Naming Conventions** - Filenames teach before you open them
- **Comments policy** - Minimal (~10 in entire codebase), only for non-obvious WHY
- **Abstraction boundaries** - See ADR 002 (Stage Independence)

Together, these create an environment optimized for rapid context acquisition.

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

- **ADR 001:** Cordon Sanitaire = working tree cleanliness
- **ADR 002:** Cost tracking = visible costs
- **ADR 003:** File organization = small composable units
- **ADR 004:** Naming conventions = consistency
- **ADR 005:** DefraDB = source of truth
- **ADR 006:** Worker architecture = managed work

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
