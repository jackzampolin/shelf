# 3. File Organization

**Date:** 2025-12-15

**Status:** Accepted

## Decision

**One concept per file. Small files over large files.**

## Go Package Structure

```
internal/
├── config/           # One package per concern
│   ├── config.go     # Manager, loading
│   └── schema.go     # Types, defaults
├── providers/
│   ├── worker.go     # Interface + pool
│   ├── openrouter.go
│   └── mistral.go    # One file per provider
└── pipeline/
    └── stages/
        └── ocr/      # One package per stage
            ├── stage.go
            └── processor.go
```

## File Size Guidelines

- **Under 200 lines:** Probably fine
- **200-400 lines:** Check if doing one thing
- **Over 400 lines:** Split it

## Go Conventions

- Package name = directory name
- One primary type per file (named after the type)
- `_test.go` files alongside implementation
- `internal/` for non-exported packages

## Why

- Fast to find (grep returns one result)
- Fits in context window
- Clear ownership
- Easy to understand in isolation

## Core Principle

**Small files enable fast understanding.**

Finding the right file: seconds, not minutes.
