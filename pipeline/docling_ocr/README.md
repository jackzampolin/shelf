# Docling OCR Stage

Parallel OCR stage using IBM's Granite Docling 258M model (MLX-optimized for Apple Silicon).

## Overview

This stage extracts **structured content** from document pages using a multimodal vision-language model, providing:

- **Layout detection** - Preserves document structure
- **Table recognition** - Structured table extraction
- **Equation recognition** - LaTeX-formatted equations
- **Code block extraction** - 50+ programming languages
- **Markdown conversion** - Clean, formatted text output

Unlike simple OCR (like `ocr-pages`), this stage outputs full **DocTags format** which preserves the semantic structure of the document.

## Model

- **Model**: `ibm-granite/granite-docling-258M-mlx`
- **Parameters**: 258M
- **Backend**: MLX (optimized for Apple Silicon)
- **Runtime**: Local (no API costs)

## Installation

```bash
# Install Docling library with MLX support
uv pip install docling

# Requires Python >= 3.12 for MLX backend
```

## Usage

```bash
# Run on a book (processes all pages sequentially)
uv run python shelf.py book <scan-id> run-stage docling-ocr

# Disable MLX (use standard backend)
uv run python shelf.py book <scan-id> run-stage docling-ocr --use-mlx false
```

## Output Schema

Each page produces `docling-ocr/page_XXXX.json`:

```python
{
  "page_num": 1,
  "docling_json": {  # Lossless JSON serialization of DoclingDocument
    "body": {
      "elements": [...]  # Layout elements (paragraphs, tables, etc.)
    },
    "metadata": {...},
    "provenance": {...}  # Full provenance information
    # Complete hierarchical structure preserved
  },
  "markdown": "# Chapter 1\n\nFull markdown text...",
  "char_count": 4523,
  "has_tables": true,
  "has_equations": false,
  "has_code": false,
  "processing_time_seconds": 2.3
}
```

### Lossless Storage

The `docling_json` field contains the **complete lossless serialization** from `DoclingDocument.save_as_json()`. This preserves:
- Full hierarchical document structure
- All metadata and provenance
- Complete element properties
- Round-trip capability (can reconstruct DoclingDocument)

You can reload the document:
```python
from docling_core.types.doc import DoclingDocument

# Load from our JSON
doc = DoclingDocument.model_validate(page_data['docling_json'])

# Or use Docling's load method
doc = DoclingDocument.load_from_json(page_file)
```

## Performance

- **Speed**: ~2-5 seconds per page (Apple Silicon M-series)
- **Cost**: Free (local processing)
- **Quality**: Excellent for structured documents (tables, equations, code)

## When to Use

**Use `docling-ocr` when:**
- You need structured extraction (tables, equations, code)
- You want to preserve document layout
- You're processing technical documents

**Use `ocr-pages` when:**
- You just need plain text
- You want faster processing (API-based)
- Document structure isn't important

## Working with Stored Documents

The stage provides helper utilities for working with stored DoclingDocuments:

```python
from pipeline.docling_ocr.tools import (
    load_docling_document,
    export_page_to_format,
    get_page_tables,
    get_page_equations
)

# Load full DoclingDocument
doc = load_docling_document(storage, page_num=42)

# Export to different formats
markdown = export_page_to_format(storage, 42, format="markdown")
html = export_page_to_format(storage, 42, format="html")
doctags = export_page_to_format(storage, 42, format="doctags")

# Extract specific elements
tables = get_page_tables(storage, 42)
equations = get_page_equations(storage, 42)

# Work with the DoclingDocument directly
for element in doc.body.elements:
    print(f"Type: {element.type}, Content: {element.text}")
```

## Downstream Stages

The lossless DoclingDocument JSON can be used by downstream stages for:
- **Table extraction**: Access structured table data
- **Equation processing**: LaTeX equations ready for rendering
- **Code block detection**: Syntax-highlighted code blocks
- **Layout-aware chunking**: Preserve document structure
- **Semantic search**: Index by document elements
- **Format conversion**: Export to any supported format

## Directory Structure

```
pipeline/docling_ocr/
├── __init__.py              # DoclingOcrStage
├── README.md                # This file
├── schemas/
│   ├── __init__.py
│   └── page_output.py       # DoclingOcrPageOutput schema
└── tools/
    ├── __init__.py
    └── processor.py         # Docling processing logic
```

## Technical Details

- **Dependencies**: No other stages (processes `source/` directly)
- **Processing**: Sequential (Docling's DocumentConverter not thread-safe)
- **Metrics**: Tracks processing time, element detection
- **Resume**: Full checkpoint support via BatchBasedStatusTracker

## Limitations

- **MLX backend**: macOS only (Apple Silicon recommended)
- **Speed**: Sequential processing (~2-5s/page), slower than parallel API-based OCR
- **Memory**: Requires ~2GB RAM for model
- **No parallelism**: Docling's MLX backend creates per-instance resources, causing memory leaks with multiple workers
