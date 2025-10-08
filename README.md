# Scanshelf - Turn Physical Books into Digital Libraries

> **⚠️ REFACTOR IN PROGRESS**
>
> This branch (`refactor/pipeline-redesign`) is undergoing a major pipeline refactor.
> See [Issue #56](https://github.com/jackzampolin/scanshelf/issues/56) for the refactor plan.
>
> **Documentation:** [docs/standards/](docs/standards/) contains production patterns for all pipeline stages.

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
ar --help
```

---

## Basic Usage

```bash
# Add a book
ar add ~/Documents/Scans/book.pdf

# Process through available stages
ar ocr <scan-id>
ar correct <scan-id>
ar fix <scan-id>

# Monitor progress
ar status <scan-id> --watch

# View library
ar library list
ar library show <scan-id>
```

---

## Documentation

**For refactor work:**
- [docs/standards/](docs/standards/) - Production patterns and standards
- [CLAUDE.md](CLAUDE.md) - AI assistant workflow

**For users:**
- [docs/MCP_SETUP.md](docs/MCP_SETUP.md) - Claude Desktop integration

---

**Powered by Claude Sonnet 4.5**
