# Scanshelf - Turn Physical Books into Digital Libraries

> **⚠️ REFACTOR IN PROGRESS**
>
> Branch: `refactor/pipeline-redesign` | [Issue #56](https://github.com/jackzampolin/scanshelf/issues/56)

---

## Quick Start

```bash
# Setup
git clone https://github.com/jackzampolin/scanshelf
cd scanshelf
git checkout refactor/pipeline-redesign

uv venv
source .venv/bin/activate
uv pip install -e .

# Configure
cp .env.example .env
# Add your OPENROUTER_API_KEY

# Verify
uv run python ar.py --help
```

---

## Usage

All commands use `uv run python ar.py`:

```bash
# Library management
uv run python ar.py library list              # View books
uv run python ar.py library show <scan-id>    # Book details

# Add books (temporary)
uv run python tools/ingest.py ~/Documents/Scans/book.pdf

# Process pipeline stages
uv run python ar.py ocr <scan-id>         # Stage 1: OCR
uv run python ar.py correct <scan-id>     # Stage 2: Correction
```

**Status:** Infrastructure and OCR/Correction stages active. Other stages coming in #48-54.

---

## Testing

```bash
# Run all tests
uv run python -m pytest tests/ -v

# Run specific modules
uv run python -m pytest tests/infra/ -v
uv run python -m pytest tests/tools/ -v
```

---

## Documentation

- [docs/standards/](docs/standards/) - Production patterns
- [CLAUDE.md](CLAUDE.md) - AI workflow guide
- [docs/MCP_SETUP.md](docs/MCP_SETUP.md) - Claude Desktop integration

---

**Powered by Claude Sonnet 4.5**
