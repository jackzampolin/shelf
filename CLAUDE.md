<critical_instructions>
## COST AWARENESS - READ THIS FIRST

**This pipeline costs real money via OpenRouter API calls.**

NEVER run these operations without explicit user approval:
- Any command that spawns LLM API calls
- `shelf serve` then submitting jobs via API
- `shelf api jobs start` or any job creation commands

Safe operations (can run freely):
- Reading files, grepping, analyzing code
- `shelf api books list`, `shelf api books get <id>`
- Running tests that use mocks
- Building and running server without submitting jobs

**Always ask first**
</critical_instructions>

<project_status>
## Project Status

This is a Go-based book digitization pipeline using DefraDB as the data layer.

**Active development branch:** `main`

The project was rewritten from Python to Go (completed in January 2025). The Go implementation uses:
- DefraDB for data storage with versioning and attribution
- Server-centric job architecture with rate-limited workers
- Parallel provider execution (OpenRouter, Mistral, DeepInfra)
- Hot-reloadable configuration
- Clean job/worker separation

### Tracking

Master tracking issue for the rewrite: [#119](https://github.com/jackzampolin/shelf/issues/119)
</project_status>

<go_implementation>
## Go Implementation

### Architecture

```
shelf/
├── cmd/shelf/           # CLI entry point (Cobra)
│   ├── main.go
│   ├── root.go
│   ├── serve.go         # Server command
│   ├── api.go           # API CLI commands (shelf api ...)
│   └── version.go       # Version command
├── internal/
│   ├── api/             # Endpoint interface + HTTP client
│   │   ├── endpoint.go  # Endpoint interface (Route + Command)
│   │   ├── registry.go  # Route registration
│   │   ├── client.go    # HTTP client for CLI
│   │   └── output.go    # Output formatting
│   ├── svcctx/          # Services context (dependency injection)
│   │   └── svcctx.go    # Services struct + extractors
│   ├── server/
│   │   ├── server.go    # HTTP server + lifecycle
│   │   └── endpoints/   # Endpoint implementations
│   │       ├── health.go          # health, ready, status
│   │       ├── jobs_*.go          # Job CRUD and management
│   │       ├── books_*.go         # Book operations
│   │       ├── metrics_*.go       # Cost tracking and metrics
│   │       ├── llmcalls.go        # LLM call history
│   │       ├── agent_logs.go      # Agent execution logs
│   │       ├── pages.go           # Page operations
│   │       ├── prompts.go         # Prompt management
│   │       ├── settings.go        # Settings management
│   │       ├── voices.go          # TTS voice management
│   │       ├── run_summary.go     # Fleet scoreboard (books by status)
│   │       ├── tts_config.go      # TTS configuration
│   │       ├── swagger.go         # OpenAPI spec + Swagger UI
│   │       ├── static.go          # Static web assets (frontend)
│   │       └── registry.go        # All() helper
│   ├── home/            # Home directory (~/.shelf)
│   ├── config/          # Config with hot-reload
│   ├── defra/           # DefraDB client + Docker management
│   ├── providers/       # LLM/OCR provider workers
│   ├── jobs/            # Job system (scheduler, pools) + implementations
│   │   ├── common/              # Shared job utilities (state, persistence, OCR/extract helpers)
│   │   ├── process_book/        # Full pipeline orchestration
│   │   │   └── job/             # Pipeline stages: metadata, extract, ocr, toc find/extract/link, structure, finalize
│   │   └── tts_generate/        # TTS audio generation (ElevenLabs + OpenAI provider strategies)
│   ├── agent/           # LLM agent with tool use
│   ├── agents/          # Specialized agents
│   │   ├── toc_finder/        # ToC detection
│   │   ├── toc_entry_finder/  # ToC entry extraction
│   │   ├── chapter_finder/    # Chapter boundary detection
│   │   ├── gap_investigator/  # Gap analysis
│   │   └── pattern_analyzer/  # Pattern detection
│   ├── llmcall/         # LLM call tracking
│   ├── metrics/         # Cost and usage metrics
│   ├── prompts/         # Prompt templates
│   ├── epub/            # ePub 3.0 generation (incl. media overlays)
│   ├── voices/          # TTS voice management (sync with providers)
│   ├── types/           # Shared types (no internal deps, avoids import cycles)
│   ├── schema/          # DefraDB schemas
│   │   └── schemas/     # GraphQL schema definitions
│   ├── ingest/          # PDF ingestion
│   ├── jobcfg/          # Job configuration
│   └── testutil/        # Testing utilities
├── web/                 # Frontend (React + TypeScript)
│   ├── src/
│   │   ├── api/         # OpenAPI client
│   │   ├── components/  # React components
│   │   ├── routes/      # Page routes
│   │   └── lib/         # Utilities
│   └── dist/            # Built assets
├── docs/decisions/      # Architecture Decision Records
├── go.mod
├── go.sum
├── Makefile
└── version/             # Version information
```

### Key Patterns

**1. DefraDB is source of truth** - Not files
```go
// Query progress from DefraDB, not filesystem
pages, _ := defra.Query(ctx, `{ pages(filter: {...}) { ... } }`)
```

**DefraDB Schema Limitations:**
- **No NonNull fields** - Use `field: String` not `field: String!`
- Schemas in `internal/schema/schemas/*.graphql`

**2. Jobs for all mutations**
```go
// All work goes through jobs
job, _ := jobManager.Submit(ctx, &OcrJob{BookID: "..."})
```

**3. Provider workers with rate limits**
```go
// Each provider has its own goroutine + rate limiter
resp, _ := providers.Get("openrouter").Chat(ctx, req)
```

**4. Metrics recorded per-call**
```go
// Every LLM call creates a metric record
metrics.RecordLLMCall(ctx, opts, resp)
```

**5. Unified endpoint pattern** - Each endpoint defines both HTTP route and CLI command (ADR 007)
```go
// internal/api/endpoint.go
type Endpoint interface {
    Route() (method, path string, handler http.HandlerFunc)
    RequiresInit() bool
    Command(getServerURL func() string) *cobra.Command
}

// Endpoints implement both HTTP handler and CLI command
// See internal/server/endpoints/ for implementations
```

**6. Services context** - Dependencies via context, not constructors (ADR 007)
```go
// Handlers extract services from context
func (e *ListJobsEndpoint) handler(w http.ResponseWriter, r *http.Request) {
    jm := svcctx.JobManagerFrom(r.Context())
    jobs, _ := jm.List(r.Context(), filter)
}

// Available extractors in internal/svcctx/:
// - svcctx.ServicesFrom(ctx)       // full *Services struct
// - svcctx.DefraClientFrom(ctx)    // *defra.Client
// - svcctx.DefraSinkFrom(ctx)      // *defra.Sink (async writes)
// - svcctx.JobManagerFrom(ctx)     // *jobs.Manager
// - svcctx.RegistryFrom(ctx)       // *providers.Registry
// - svcctx.SchedulerFrom(ctx)      // *jobs.Scheduler
// - svcctx.LoggerFrom(ctx)         // *slog.Logger
// - svcctx.HomeFrom(ctx)           // *home.Dir
// - svcctx.ConfigStoreFrom(ctx)    // config.Store
// - svcctx.MetricsQueryFrom(ctx)   // *metrics.Query
// - svcctx.LLMCallStoreFrom(ctx)   // *llmcall.Store
// - svcctx.PromptResolverFrom(ctx) // *prompts.Resolver
```

### CLI Commands

**Prefer `shelf api` over raw curl** - The CLI commands are easier to use and handle auth/formatting:

```bash
# Server management
shelf serve                    # Start server (with DefraDB)

# API commands (talk to running server) - USE THESE INSTEAD OF CURL
shelf api health               # Basic health check
shelf api ready                # Readiness check (includes DefraDB)
shelf api status               # Detailed status
shelf api run-summary          # Fleet scoreboard: books by status + recovery hints
shelf api tts-config           # Get TTS configuration and available voices

# Book management
shelf api books list                     # List all books
shelf api books get <id>                 # Get book details
shelf api books ingest <pdf-files...>    # Ingest PDF scans (--title, --author, --stitch)
shelf api books cost <book_id>           # Get book processing cost

# Book exports
shelf api books export-epub <book_id>            # Export book as ePub
shelf api books download-epub <book_id>          # Download ePub file
shelf api books export-storyteller <book_id>     # Export EPUB with Media Overlays for Storyteller
shelf api books download-storyteller <book_id>   # Download Storyteller EPUB

# Book audio (TTS) - COSTS MONEY
shelf api books generate-audio <book_id>              # Start TTS audiobook generation (--provider elevenlabs|openai, --voice)
shelf api books audio <book_id>                       # Get audio status and files
shelf api books download-audio <book_id> <chapter_idx> # Download chapter audio (-o output path)

# Job management
shelf api jobs list            # List all jobs (--status, --type, --book)
shelf api jobs list --status running --type process-book
shelf api jobs get <id>        # Get job details
shelf api jobs start <book_id> # Start processing a book (--variant, --reset-from, --force)
shelf api jobs status <book_id> # Get job status for a book
shelf api jobs create --type process-book
shelf api jobs update <id> --status completed
shelf api jobs retry <id>      # Retry a failed job
shelf api jobs delete <id>     # Delete a job

# Metrics and monitoring
shelf api metrics list         # List all metrics
shelf api metrics summary      # Get metrics summary
shelf api metrics cost         # Get total cost
shelf api llmcalls list        # List LLM call history (--book-id, --job-id, --provider, --failed, ...)
shelf api llmcalls get <id>    # Get a single LLM call
shelf api llmcalls counts <book-id> # LLM call counts for a book

# TTS voice management
shelf api voices list                  # List voices
shelf api voices sync                  # Sync voices from provider
shelf api voices create <voice_id>     # Add a voice
shelf api voices set-default <voice_id> # Set default voice
shelf api voices delete <voice_id>     # Remove a voice

# Settings and configuration
shelf api settings list        # List all settings
shelf api settings get <key>   # Get a setting
shelf api settings set <key>   # Update a setting
shelf api settings reset <key> # Reset a setting to default
```

**HTTP-only endpoints (no CLI wiring in `cmd/shelf/api.go`; used by the web UI):**
book chapters, rerun-toc, book upload, jobs status-detailed, detailed metrics,
agent logs, prompts (global + per-book), pages/page images, and `/swagger.json` + Swagger UI.

**Debug config:** Agent logs are only saved when `defaults.debug_agents` is `true` in job config.

### Environment

```bash
# Build and install (builds both frontend and backend)
make install

# Run server
shelf serve

# Run tests
make test

# Development - backend only (faster iteration)
make build:backend
./build/shelf serve

# View all available make targets
make help
```

### Reference Projects

**defra-mongo-connector** - `/Users/johnzampolin/go/src/github.com/sourcenetwork/defra-mongo-connector`
Use this for patterns on:
- CLI structure (Cobra commands, flags)
- Docker container management (`internal/dockerutil/`)
- Config with viper + hot-reload (`internal/connector/config.go`)
- Integration testing patterns

**DefraDB source** - `/Users/johnzampolin/go/src/github.com/sourcenetwork/defradb`
Local copy of DefraDB for understanding the database internals, client API, and query patterns.

**DefraDB docs** - https://docs.source.network/
</go_implementation>

<git_workflow>
## Git Workflow

**Branch strategy:**
- `main` - Active development (Go implementation)

**Commits:**
```bash
<type>: <imperative summary>

<body explaining what/why>

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
```

**Commit types:** feat, fix, refactor, docs, chore, test

**Do NOT:**
- Force push to `main`
- Skip the co-author attribution
</git_workflow>

<architecture_decisions>
## Architecture Decisions

`docs/decisions/` contains Architecture Decision Records (ADRs).

**Core ADRs:**
- **000 (Information Hygiene)** - Context clarity as first principle
- **001 (Cordon Sanitaire)** - Temporal boundaries (past/present/future)
- **002 (Cost Tracking)** - Economics shape architecture
- **003 (File Organization)** - Small files, one concept per file
- **004 (Naming Conventions)** - Consistent naming patterns
- **005 (DefraDB Source of Truth)** - DefraDB as single source of truth
- **006 (Worker Architecture)** - Pool-based worker architecture
- **007 (Services Context)** - Dependency injection via context, unified endpoint pattern
- **008 (Config and Prompts in Database)** - Store configuration in DefraDB
- **009 (BookState Repository Pattern)** - Repository pattern for book pipeline state
- **010 (Async-Only DB Writes for Per-Book Operations)** - Per-book writes go through the async sink
- **011 (Zero Marginal Cost for Local Inference)** - Local inference treated as zero marginal cost

Read the ADRs in `docs/decisions/` to understand design rationale.
</architecture_decisions>

<remember>
## Remember - Critical Checklist

**1. COST AWARENESS**
- NEVER run LLM operations without approval
- Test with mocks, not real API calls
- Jobs that call LLMs: `process-book` (all pipeline stages), `tts-generate`, `tts-generate-openai`

**2. DEFRADB**
- All state in DefraDB, not files
- Jobs for mutations
- Provider workers for rate limits
- **NO NonNull fields** - DefraDB doesn't support `!` in GraphQL schemas (e.g., use `key: String` not `key: String!`)

**3. ENDPOINT PATTERN**
- Each endpoint defines both HTTP route AND CLI command
- Services come from context (`svcctx.JobManagerFrom(ctx)`)
- Add new endpoints to `internal/server/endpoints/`
- Register in `endpoints.All()` helper

**4. JOB SYSTEM**
- Job implementations in `internal/jobs/*/`
- Each job type has its own package
- Jobs communicate via DefraDB state changes
- Use `shelf api jobs start <book-id>` to process books

**5. TESTING**
- Run tests: `make test`
- Run all tests (including integration): `make test:all`
- Test with coverage: `make test:coverage`
- Frontend tests: `make web:test`
- Use mocks for LLM/OCR providers in tests
</remember>
