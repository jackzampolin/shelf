# Shelf

Turn physical books into digital libraries using vision-powered OCR and LLMs.

## Overview

Shelf is a book digitization pipeline that transforms scanned book pages into structured ePub files using:
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

## Pipeline Stages

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
shelf api books ingest <pdf>     # Ingest a PDF scan
shelf api books get <id>         # Get book details

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
providers:
  openrouter:
    api_key: "your-key"
    rate_limit: 10  # requests per second

defaults:
  debug_agents: false
  max_retries: 3
```

See the web UI settings page or `shelf api settings get` for current configuration.

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
