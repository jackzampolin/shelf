# Shelf

Turn owned book sources into structured books and audiobooks. Shelf accepts
native EPUB text directly, embedded-text PDFs, and image-only scans; OCR is a
source adapter, not a requirement for every book.

## Overview

Shelf is a book digitization pipeline that transforms source books into structured ePub files using:
- Direct EPUB package/navigation/spine import with no inference
- Embedded PDF text recovery when a scan already carries a faithful text layer
- Multi-provider OCR with consensus blending
- LLM-powered content analysis and structure extraction
- DefraDB for data storage with versioning and attribution
- Server-centric job architecture with rate-limited workers
- React-based web UI for monitoring and configuration

## Status

**Production-ready Go implementation** with DefraDB data layer (completed January 2025).

See [#119](https://github.com/jackzampolin/shelf/issues/119) for the rewrite tracking issue.

## Quick Start

### Prerequisites

- Go 1.21 or later
- Docker (for DefraDB)
- Bun (for frontend development)
- OpenRouter API key

### Installation

```bash
# Clone the repository
git clone https://github.com/jackzampolin/shelf.git
cd shelf

# Build and install (builds frontend + backend)
make install

# Set up your API key
export OPENROUTER_API_KEY="your-key-here"
# Or create ~/.shelf/config.yaml with your configuration

# Start the server (starts DefraDB automatically)
shelf serve
```

The web UI will be available at http://localhost:8080

### Read-only research MCP

Run a separate, mutation-free MCP boundary over an existing Shelf server:

```bash
shelf mcp --shelf-url http://127.0.0.1:8080 --port 18081
```

Defra and other MCP clients connect at `http://127.0.0.1:18081/mcp`. The server
exposes only bounded book metadata, structure listing, lexical/regex passage
search, bounded passage reads, and exact quotation validation. Every text result
includes the current canonical structure digest; processing, repair, raw
DefraDB, whole-book dumps, and other mutations are intentionally absent.

### Development

```bash
# Build backend only (faster for Go development)
make build:backend
./build/shelf serve

# Run frontend dev server (in another terminal)
make web:dev

# Run tests
make test

# View all available targets
make help
```

## Architecture

- **DefraDB**: Source of truth for all book data, pages, and processing state
- **Job System**: All mutations go through a job queue with proper scheduling
- **Provider Workers**: Rate-limited workers for OpenRouter, Mistral, DeepInfra
- **Unified Endpoints**: Each endpoint defines both HTTP route and CLI command
- **Services Context**: Dependency injection via context (no global state)

See [CLAUDE.md](CLAUDE.md) for detailed development context and patterns.

## Source paths

| Source | Shelf path | Inference |
|---|---|---|
| EPUB | `books import-epub` → terminal metadata/navigation/chapters | None |
| PDF with embedded text | PDF ingest → `books repair-pdf-text` → downstream structure | Structure only |
| Image-only PDF scan | PDF ingest → OCR → ToC → structure | OCR + structure |

`import-epub` preflights the complete archive, preserves the original bytes and
SHA-256, and runs synchronously to a terminal `complete` book. Re-importing the
same bytes returns the existing Shelf book.

## Scan pipeline stages

The book processing pipeline includes:

1. **Ingest** - Extract pages from PDF scans
2. **OCR** - Multi-provider OCR with consensus blending
3. **Label** - Classify page structure (headers, body, footnotes)
4. **ToC Extraction** - Find and extract table of contents
5. **ToC Linking** - Link ToC entries to chapter locations
6. **Structure** - Extract unified chapter/section structure
7. **Finalize** - Complete processing and prepare for export

## CLI Commands

```bash
# Server
shelf serve                      # Start server

# Books
shelf api books list             # List all books
shelf api books import-epub <epub> # Direct terminal import; skip OCR/LLMs
shelf api books ingest <pdf>     # Ingest a PDF scan
shelf api books ingest --stitch <dir> # Ingest a directory of numbered PDF parts as books
shelf api books get <id>         # Get book details
shelf api books chapters <id>    # Inspect imported/structured chapters
shelf api books repair-toc-range <id> --start 1052 --end 1053 --reason "verified printed contents"

# Jobs
shelf api jobs start <book-id>   # Start processing a book
shelf api jobs status <book-id>  # Check job status
shelf api jobs list              # List all jobs

# Metrics
shelf api metrics summary        # View cost and usage metrics

# Health
shelf api health                 # Basic health check
shelf api ready                  # Readiness (includes DefraDB)
shelf api status                 # Detailed server status
```

Run `shelf --help` or `shelf api <command> --help` for full command documentation.

## Configuration

Configuration lives in `~/.shelf/config.yaml` with hot-reload support.

Example configuration:

```yaml
llm_providers:
  openrouter:
    api_key: "your-key"
    rate_limit: 10  # requests per second
    max_concurrency: 32  # concurrent in-flight requests

defaults:
  debug_agents: false
  max_retries: 3
```

See the web UI settings page or `shelf api settings get` for current configuration.
For batch runs, `rate_limit` and per-provider `max_concurrency` are the hardware/API
capacity knobs; the scheduler allocates those slots across queued books.

## Documentation

- [CLAUDE.md](CLAUDE.md) - AI development context and architecture
- [docs/decisions/](docs/decisions/) - Architecture Decision Records (ADRs)
- API documentation available at http://localhost:8080/swagger when server is running

## Cost Awareness

⚠️ **This pipeline makes real API calls that cost money.**

Always review costs before running:
```bash
shelf api metrics summary        # View current costs
shelf api books cost <book-id>   # Estimate book processing cost
```

## Testing

```bash
make test              # Run Go tests
make test:all          # Run all tests (including integration)
make test:coverage     # Generate coverage report
make web:test          # Run frontend tests
```

Tests use mocks for LLM/OCR providers - no API calls are made during testing.

## License

See [LICENSE](LICENSE) for details.
