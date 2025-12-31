# 4. Naming Conventions

**Date:** 2025-12-15

**Status:** Accepted

## Decision

**Consistent naming prevents bugs and enables discovery.**

## Go Naming

| Thing | Convention | Example |
|-------|------------|---------|
| Packages | lowercase, underscores OK | `config`, `extract_toc` |
| Files | lowercase, underscore | `rate_limiter.go` |
| Exported types | PascalCase | `type Worker interface` |
| Unexported | camelCase | `func processPage()` |
| Interfaces | -er suffix when possible | `Reader`, `Processor` |

## Multi-Word Packages

Go allows underscores in package names for multi-word concepts:

```
internal/prompts/extract_toc/
internal/agents/toc_finder/
internal/jobs/process_pages/
```

This differs from Python's hyphenated stage names. In Go, underscores are idiomatic.

## ADR Files

**Format:** `NNN-kebab-case.md`

```
000-information-hygiene.md
005-defradb-source-of-truth.md
```

## Core Principle

**Filenames teach before you open them.**

Consistency prevents bugs. Good naming frontloads understanding.
