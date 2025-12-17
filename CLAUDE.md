<critical_instructions>
## COST AWARENESS - READ THIS FIRST

**This pipeline costs real money via OpenRouter API calls.**

NEVER run these operations without explicit user approval:
- Any command that spawns LLM API calls
- `shelf.py book <scan-id> process` - Full pipeline processing (Python)
- `shelf.py book <scan-id> stage <stage> run` - Single stage processing (Python)
- `shelf serve` then submitting jobs via API (Go)

Safe operations (can run freely):
- Reading files, grepping, analyzing code
- `shelf.py library list`, `shelf.py book <scan-id> info`
- Running tests that use mocks
- Building and running without API calls

**Always ask first**
</critical_instructions>

<project_status>
## Project Status: Go Rewrite

This project has TWO implementations:
1. **Python (legacy)** - In `main` branch, functional but being replaced
2. **Go (new)** - In `go-rewrite` branch, under active development

### Branch Strategy

```bash
# Development uses git worktrees for parallel work
git worktree add ../shelf-python main        # Reference Python implementation
git worktree add ../shelf-go go-rewrite      # Active Go development
```

### Which Branch Am I On?

Check your current branch before making changes:
```bash
git branch --show-current
```

- **If `main`:** You're in the Python codebase (legacy reference)
- **If `go-rewrite`:** You're in the Go codebase (active development)

### Tracking

Master tracking issue: [#119](https://github.com/jackzampolin/shelf/issues/119)
All Go rewrite issues are labeled `go-rewrite`.
</project_status>

<go_implementation>
## Go Implementation

### Architecture

```
shelf-go/
├── cmd/shelf/           # CLI entry point (Cobra)
│   ├── main.go
│   ├── root.go
│   ├── serve.go         # Server command
│   └── api.go           # API CLI commands (shelf api ...)
├── internal/
│   ├── api/             # Endpoint interface + HTTP client
│   │   ├── endpoint.go  # Endpoint interface (Route + Command)
│   │   ├── registry.go  # Route registration
│   │   └── client.go    # HTTP client for CLI
│   ├── svcctx/          # Services context (dependency injection)
│   │   └── svcctx.go    # Services struct + extractors
│   ├── server/
│   │   ├── server.go    # HTTP server + lifecycle
│   │   └── endpoints/   # Endpoint implementations
│   │       ├── health.go    # health, ready, status
│   │       ├── jobs.go      # CRUD for jobs
│   │       └── registry.go  # All() helper
│   ├── home/            # Home directory (~/.shelf)
│   ├── config/          # Config with hot-reload
│   ├── defra/           # DefraDB client + Docker management
│   ├── providers/       # LLM/OCR provider workers
│   ├── jobs/            # Job system (scheduler, workers)
│   ├── agent/           # LLM agent with tool use
│   └── pipeline/
│       ├── stage.go     # Stage interface
│       ├── registry.go  # Stage registry
│       └── stages/      # Stage implementations
├── docs/decisions/      # Architecture Decision Records
├── go.mod
└── Makefile
```

### Key Patterns

**1. DefraDB is source of truth** - Not files
```go
// Query progress from DefraDB, not filesystem
pages, _ := defra.Query(ctx, `{ pages(filter: {...}) { ... } }`)
```

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
// - svcctx.DefraClientFrom(ctx)
// - svcctx.JobManagerFrom(ctx)
// - svcctx.RegistryFrom(ctx)
// - svcctx.SchedulerFrom(ctx)
// - svcctx.LoggerFrom(ctx)
```

### CLI Commands

```bash
# Server management
shelf serve                    # Start server (with DefraDB)

# API commands (talk to running server)
shelf api health               # Basic health check
shelf api ready                # Readiness check (includes DefraDB)
shelf api status               # Detailed status

# Job management
shelf api jobs list            # List all jobs
shelf api jobs list --status running --type ocr-pages
shelf api jobs get <id>        # Get job details
shelf api jobs create --type ocr-pages
shelf api jobs update <id> --status completed
```

### Environment

```bash
# Go setup
cd shelf-go  # or wherever your go-rewrite worktree is
go build -o shelf ./cmd/shelf
./shelf --help

# Tests
go test ./...
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

<python_implementation>
## Python Implementation (Legacy Reference)

The Python code in `main` branch is the reference implementation.

### Local Paths

```bash
# Python code (main branch worktree)
/Users/johnzampolin/go/src/github.com/jackzampolin/shelf

# Book data (scans, OCR output, etc.)
~/Documents/shelf/
```

### What to Reference

Use the Python code to understand:
- Stage logic and prompts (`pipeline/*/`)
- Data flow between stages
- LLM call patterns (`infra/llm/`)
- Config schema (`infra/config/schemas.py`)

### Key Files

```
pipeline/
├── ocr_pages/           # OCR with multi-provider + blend
├── label_structure/     # Page block classification
├── extract_toc/         # ToC extraction
├── link_toc/            # ToC linking
├── common_structure/    # Unified structure
└── epub_output/         # ePub generation

infra/
├── llm/                 # LLM client (OpenRouter)
├── ocr/                 # OCR provider base
├── pipeline/            # Stage base classes
└── config/              # Configuration
```
</python_implementation>

<git_workflow>
## Git Workflow

**Branch strategy:**
- `main` - Python implementation (legacy, reference only)
- `go-rewrite` - Go implementation (active development)

**Commits on `go-rewrite`:**
```bash
<type>: <imperative summary>

<body explaining what/why>

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
```

**Commit types:** feat, fix, refactor, docs, chore, test

**Do NOT:**
- Force push to any branch
- Commit directly to `main` (it's frozen for reference)
- Skip the co-author attribution
</git_workflow>

<architecture_decisions>
## Architecture Decisions

`docs/decisions/` contains ADRs for both implementations.

**Core ADRs (apply to both):**
- **000 (Information Hygiene)** - Context clarity as first principle
- **001 (Cordon Sanitaire)** - Temporal boundaries (past/present/future)
- **002 (File Organization)** - Small files, one concept per file
- **003 (Cost Tracking)** - Economics shape architecture

**Python-specific (in main):**
- 001-007 original Python ADRs

**Go-specific:**
- **004 (DefraDB Integration)** - Docker-managed DefraDB as data layer
- **005 (Scheduler Architecture)** - Job distribution with provider rate limits
- **006 (Worker Architecture)** - Concurrent workers with result channels
- **007 (Services Context)** - Dependency injection via context, unified endpoint pattern
</architecture_decisions>

<remember>
## Remember - Critical Checklist

**1. CHECK YOUR BRANCH**
```bash
git branch --show-current
```
- `main` = Python (reference only)
- `go-rewrite` = Go (active development)

**2. COST AWARENESS**
- NEVER run LLM operations without approval
- Test with mocks, not real API calls

**3. DEFRADB (Go)**
- All state in DefraDB, not files
- Jobs for mutations
- Provider workers for rate limits

**4. ENDPOINT PATTERN (Go)**
- Each endpoint defines both HTTP route AND CLI command
- Services come from context (`svcctx.JobManagerFrom(ctx)`)
- Add new endpoints to `internal/server/endpoints/`
- Register in `endpoints.All()` helper

**5. REFERENCE PYTHON**
- Stage logic lives in `pipeline/*/`
- Prompts in `*/prompt.py`
- Use as reference, don't modify

**6. TESTING**
- Go: `go test ./...`
- Python: `uv run python -m pytest tests/`
</remember>
