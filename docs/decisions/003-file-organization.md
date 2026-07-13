# 3. File Organization

**Date:** 2025-12-15

**Status:** Accepted

## Decision

**One concept per file. Small files over large files.**

## Go Package Structure

```
internal/
├── config/           # Configuration management
│   ├── config.go     # Manager, loading, hot-reload
│   └── schema.go     # Types, defaults
├── providers/        # LLM and OCR provider clients
│   ├── provider.go   # Interfaces (LLMClient, OCRProvider)
│   ├── openrouter.go # One file per provider
│   ├── mistral.go
│   └── registry.go   # Provider registry
├── jobs/             # Job system
│   ├── job.go        # Job interface, work units
│   ├── worker.go     # Worker wrapping providers
│   ├── scheduler.go  # Job orchestration
│   └── manager.go    # DefraDB persistence
└── server/           # HTTP API
    ├── server.go
    └── routes.go
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

## Cohesion Exception (2026-07-06)

The 400-line limit applies to multi-concept files. A file that is one
cohesive concept — one provider client, one event loop, one builder —
may exceed 400 lines when splitting it would fragment a single concept
across arbitrary shards. The audited list of such files lives in
`docs/superpowers/specs/2026-07-01-large-file-breakup-design.md`
(Tier 3). Future audits should apply the one-concept test before
flagging files on that list.
