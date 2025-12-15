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
├── internal/
│   ├── home/            # Home directory (~/.shelf)
│   ├── config/          # Config with hot-reload
│   ├── defra/           # DefraDB client + Docker management
│   ├── providers/       # LLM/OCR provider workers
│   ├── jobs/            # Job system
│   ├── metrics/         # Metrics recording
│   ├── server/          # HTTP API
│   └── pipeline/
│       ├── stage.go     # Stage interface
│       ├── registry.go  # Stage registry
│       └── stages/      # Stage implementations
│           ├── ocr_pages/
│           ├── label_structure/
│           └── ...
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

### Environment

```bash
# Go setup
cd shelf-go  # or wherever your go-rewrite worktree is
go build -o shelf ./cmd/shelf
./shelf --help

# Tests
go test ./...
```

### Reference

- Pattern reference: `/Users/johnzampolin/go/src/github.com/sourcenetwork/defra-mongo-connector`
- DefraDB docs: https://docs.source.network/
</go_implementation>

<python_implementation>
## Python Implementation (Legacy Reference)

The Python code in `main` is the reference implementation. Use it to understand:
- Stage logic and prompts
- Data flow between stages
- LLM call patterns

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

### Environment

```bash
# Python setup
uv venv && source .venv/bin/activate
uv pip install -e .
uv run python shelf.py --help

# Tests
uv run python -m pytest tests/
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

**Go-specific (being added):**
- TBD as Go implementation progresses
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

**4. REFERENCE PYTHON**
- Stage logic lives in `pipeline/*/`
- Prompts in `*/prompt.py`
- Use as reference, don't modify

**5. TESTING**
- Go: `go test ./...`
- Python: `uv run python -m pytest tests/`
</remember>
