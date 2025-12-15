# 4. Naming Conventions

**Date:** 2025-12-15

**Status:** Accepted

## Decision

**Consistent naming prevents bugs and enables discovery.**

## Go Naming

| Thing | Convention | Example |
|-------|------------|---------|
| Packages | lowercase, short | `config`, `providers` |
| Files | lowercase, underscore | `rate_limiter.go` |
| Exported types | PascalCase | `type Worker interface` |
| Unexported | camelCase | `func processPage()` |
| Interfaces | -er suffix when possible | `Reader`, `Processor` |

## Stage Names

**Format:** `lowercase-with-hyphens`

Used in: CLI args, DefraDB collections, logs, metrics.

```
ocr-pages
label-structure
extract-toc
link-toc
```

## ADR Files

**Format:** `NNN-kebab-case.md`

```
000-information-hygiene.md
005-defradb-source-of-truth.md
```

## Why Consistency Matters

Mixed conventions (hyphens vs underscores) caused real bugs in the Python version. Stage name lookups failed between CLI, storage, and logs.

## Core Principle

**Filenames teach before you open them.**

Consistency prevents bugs. Good naming frontloads understanding.
