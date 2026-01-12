# Full Codebase Audit

Perform a comprehensive, multi-pass audit of the codebase against docs/decisions/*.

## Instructions

1. **Read the audit checklist** at `docs/audit-checklist.md` first
2. **Create a TodoWrite list** with all audit passes
3. **Work sequentially** through each pass
4. **ASK before fixing** - list findings, get approval, then fix
5. **Mark complete** as you go

## Audit Passes

### Pass 1: Top-Down Architecture Review
Examine high-level structure:
- `cmd/shelf/` - Entry points should just wire things together
- `internal/` - Check package dependencies, no cycles
- Import graph follows dependency direction (lower packages don't import higher)

### Pass 2: Bottom-Up Implementation Review
Check each file against ADRs:
- File sizes: warn if >400 lines (ADR 003)
- One concept per file (ADR 003)
- Naming conventions (ADR 004): hyphen-case for stages, PascalCase exports
- No TODO comments in code (ADR 001)

### Pass 3: Context/Services Usage Audit
Verify ADR 007 compliance:
- HTTP handlers use `svcctx.*From(ctx)` extractors
- Jobs use `svcctx.ServicesFrom(ctx)` in Start/OnComplete
- No services passed via constructor (except at initialization)
- Check for any naked struct field access that should use context

### Pass 4: DefraDB/Storage Usage Audit
Verify ADR 005 compliance:
- All state changes go through DefraDB (not filesystem)
- Writes use DefraSink appropriately:
  - `Send()` for fire-and-forget (metrics, logs)
  - `SendSync()` when docID needed
- Queries use proper GraphQL patterns
- No direct file writes for state

### Pass 5: Job/Worker Pattern Audit
Verify ADR 006 compliance:
- All work flows through job system
- Workers wrap providers with rate limiting
- Metrics recorded per LLM/OCR call (ADR 002)
- Jobs implement full interface (Start, OnComplete, Done, Status)

### Pass 6: Package-by-Package Deep Dive
For each package in `internal/`, check:
- Purpose is clear from package name
- Files are focused (<400 lines)
- Exports are intentional
- Tests exist for critical paths

Packages to audit:
- `agent/` - LLM agent with tool use
- `api/` - Endpoint interface + HTTP client
- `config/` - Config with hot-reload
- `defra/` - DefraDB client + Docker management
- `home/` - Home directory (~/.shelf)
- `ingest/` - Book scan intake
- `jobs/` - Job system (scheduler, workers, manager)
- `metrics/` - Cost tracking
- `pipeline/` - Stage interface and implementations
- `providers/` - LLM/OCR provider clients
- `schema/` - GraphQL schema registry
- `server/` - HTTP server + lifecycle
- `svcctx/` - Services context
- `testutil/` - Test utilities

## Execution Pattern

For EACH area:
```
1. grep/read relevant files
2. list findings (violations, concerns, questions)
3. ASK USER: "Found X issues in Y. Fix these? [list specifics]"
4. wait for approval
5. make approved fixes only
6. mark todo complete
7. move to next area
```

## Output

At the end, summarize:
- Total issues found
- Issues fixed
- Issues deferred (with reasons)
- Suggestions for future work
