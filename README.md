# Shelf

Turn physical books into digital libraries using vision-powered OCR and LLMs.

## Status: Go Rewrite in Progress

This project is undergoing a major rewrite from Python to Go with DefraDB as the data layer.

**Tracking:** See [#119](https://github.com/jackzampolin/shelf/issues/119) for the master tracking issue.

**Branch strategy:**
- `main` - Current Python implementation (reference)
- `go-rewrite` - Go implementation in progress

## Python Implementation (Legacy)

The Python implementation in `main` is functional but being replaced. See `CLAUDE.md` for development context.

```bash
# Python setup (legacy)
uv venv && source .venv/bin/activate
uv pip install -e .
uv run python shelf.py --help
```

## Go Implementation (In Progress)

The Go rewrite lives in the `go-rewrite` branch. Key improvements:
- DefraDB for data storage with versioning and attribution
- Server-centric job architecture
- Parallel provider execution
- Clean metrics from the ground up

```bash
# Go setup (coming soon)
git checkout go-rewrite
go build -o shelf ./cmd/shelf
./shelf --help
```

## Documentation

- [CLAUDE.md](CLAUDE.md) - AI development context
- [docs/decisions/](docs/decisions/) - Architecture Decision Records
