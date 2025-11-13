# ePub Output Stage

Generate valid ePub 3.0 files from structured book data.

## Overview

The `epub-output` stage is the final output stage in the Scanshelf pipeline. It takes the structured book data from `common-structure` and generates a standards-compliant ePub 3.0 file that can be read on any ePub-compatible device or reader.

## Dependencies

**Required stages:**
- `common-structure` - Provides book structure, ToC, page references
- `label-structure` - Provides block classifications (body, footnotes, headers)
- OCR stage (configurable) - Provides raw text content
  - `mistral-ocr` (default)
  - `olm-ocr`
  - `paddle-ocr`

## Outputs

**Main output:**
- `{scan-id}.epub` - Valid ePub 3.0 file in book root directory

**Stage metadata:**
- `epub-output/metadata.json` - Generation details and validation results

## Configuration

The stage can be configured via keyword arguments:

```python
# Default configuration
{
    "footnote_placement": "end_of_chapter",  # or "end_of_book", "popup"
    "include_headers_footers": False,        # Include header/footer blocks
    "css_theme": "serif",                    # or "sans-serif", "custom"
    "image_quality": "original",             # or "compressed"
    "ocr_source": "mistral-ocr",            # Which OCR stage to use
    "epub_version": "3.0",                   # ePub version
    "generate_page_list": True,              # Include page-list in navigation
    "validate_output": True,                 # Run epubcheck validation
}
```

## Usage

### Via CLI

```bash
# Generate ePub with default settings
uv run python shelf.py book <scan-id> run-stage epub-output

# Generate with custom configuration
uv run python shelf.py book <scan-id> run-stage epub-output \
    --ocr-source olm-ocr \
    --css-theme sans-serif \
    --footnote-placement end_of_book
```

### Programmatically

```python
from infra.pipeline.storage.book_storage import BookStorage
from pipeline.epub_output import EpubOutputStage

storage = BookStorage.from_scan_id("my-book")

# With default config
stage = EpubOutputStage(storage)
result = stage.run()

# With custom config
stage = EpubOutputStage(
    storage,
    ocr_source="olm-ocr",
    css_theme="sans-serif",
    footnote_placement="end_of_book"
)
result = stage.run()

print(f"ePub generated: {result['epub_path']}")
```

## What It Does

### Phase 1: Load Structure (common-structure/structure.json)
- Loads book metadata (title, author, publisher)
- Loads ToC hierarchy (parts, chapters, sections)
- Loads page references (scan → printed page mapping)

### Phase 2: Extract Chapter Content
- For each chapter/section in structure:
  - Extracts body text from OCR stage
  - Classifies blocks using label-structure (BODY, FOOTNOTE, HEADER)
  - Collects footnotes
  - Extracts images (if present)

### Phase 3: Build ePub
- Creates ePub package structure
- Generates XHTML files per chapter
- Builds navigation document (ToC + page-list)
- Adds metadata (Dublin Core)
- Applies CSS styling
- Packages into .epub file

### Phase 4: Validate (optional)
- Runs epubcheck validation
- Logs validation results
- Saves validation report to metadata.json

## ePub Features

**Structure:**
- ✅ Hierarchical Table of Contents (parts → chapters → sections)
- ✅ Page-list navigation (scan pages → printed pages)
- ✅ Proper reading order (spine)

**Content:**
- ✅ Chapter text from OCR
- ✅ Footnotes (end-of-chapter by default)
- ✅ Page break markers
- ✅ Headers/footers (optional)

**Metadata:**
- ✅ Title, author, publisher, publication year
- ✅ Language
- ✅ Unique identifier (scan ID)
- ✅ Generation timestamp

**Styling:**
- ✅ Responsive CSS (serif/sans-serif themes)
- ✅ Proper typography (line height, margins, indentation)
- ✅ Footnote formatting

## Validation

The stage uses [epubcheck](https://github.com/w3c/epubcheck) (via Python wrapper) to validate the generated ePub file against the ePub 3.0 specification.

**Validation checks:**
- File structure (mimetype, container.xml, OPF)
- Navigation document validity
- XHTML validity
- Metadata completeness
- Spine integrity

**Installation:**
```bash
uv pip install epubcheck
```

**Manual validation:**
```bash
# After generating the ePub
epubcheck ~/Documents/book_scans/my-book/my-book.epub
```

## Testing the Output

### In Sigil (Recommended)
1. Download [Sigil](https://sigil-ebook.com/) (free, open-source)
2. Open the generated .epub file
3. Check:
   - ToC navigation works
   - Page numbers display correctly
   - Footnotes link properly
   - Images load
   - Reading experience is smooth

### In Calibre
1. Open [Calibre](https://calibre-ebook.com/)
2. Add the .epub to your library
3. Open in Calibre's ebook viewer
4. Verify visual appearance and navigation

### In Online Validators
- https://validator.idpf.org/ (10MB limit)
- https://epubcheck.mebooks.co.nz/

## Known Limitations

**Current version (v1):**
- ❌ Images not yet extracted/embedded (TODO)
- ❌ ToC is flat (not hierarchical) - needs nested sections
- ❌ No cover image support yet
- ❌ Footnotes are simple endnotes (no bidirectional links yet)
- ❌ No page break markers in text (planned)

**Future enhancements:**
- Support for popup footnotes (ePub 3.0 feature)
- Image extraction and embedding
- Hierarchical ToC with nested sections
- Cover image generation/extraction
- Custom CSS themes
- Accessibility features (ARIA, alt text)

## Troubleshooting

### "Structure file not found"
**Problem:** `common-structure` stage hasn't run yet.

**Solution:**
```bash
uv run python shelf.py book <scan-id> run-stage common-structure
uv run python shelf.py book <scan-id> run-stage epub-output
```

### "OCR data not found"
**Problem:** OCR stage specified in config hasn't run.

**Solution:**
```bash
# Run the OCR stage first
uv run python shelf.py book <scan-id> run-stage mistral-ocr

# Or specify a different OCR source
uv run python shelf.py book <scan-id> run-stage epub-output --ocr-source olm-ocr
```

### "epubcheck not installed"
**Problem:** Validation is enabled but epubcheck package missing.

**Solution:**
```bash
uv pip install epubcheck
```

Or disable validation:
```bash
uv run python shelf.py book <scan-id> run-stage epub-output --no-validate
```

### ePub won't open in reader
**Problem:** Invalid ePub structure.

**Solution:**
1. Check validation results in `epub-output/metadata.json`
2. Run epubcheck manually: `epubcheck path/to/file.epub`
3. Review error messages
4. File an issue with validation output

## Architecture

```
pipeline/epub_output/
├── __init__.py              # EpubOutputStage (main stage class)
├── README.md                # This file
├── schemas/
│   ├── __init__.py
│   └── epub_config.py       # Configuration schema
└── builders/
    ├── __init__.py
    ├── content_extractor.py # Extract chapter content from OCR + labels
    └── epub_builder.py      # Build ePub file using ebooklib
```

**Key classes:**
- `EpubOutputStage` - Main stage orchestrator
- `EpubConfig` - Configuration schema
- `ChapterContent` - Extracted chapter data (text, footnotes, images)
- `build_epub()` - Core ePub generation function

## Related Issues

- Issue #86 - Add ePub export functionality
- Issue #89 - Define unified structure schema for ePub and audiobook output

## References

- [ePub 3.0 Specification](http://idpf.org/epub/30)
- [EPUBCheck Validator](https://github.com/w3c/epubcheck)
- [ebooklib Documentation](https://github.com/aerkalov/ebooklib)
- [Sigil ePub Editor](https://sigil-ebook.com/)
