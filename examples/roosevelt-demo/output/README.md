# Roosevelt Demo - Sample Output

This directory contains sample outputs from processing Theodore Roosevelt's autobiography through the Scanshelf pipeline.

## What's Included

### Metadata
- `metadata/metadata.json` - Complete structure metadata including:
  - Book information (title, author, publisher, year)
  - Processing statistics (pages, chapters, costs)
  - Chapter breakdown with page ranges
  - Cost breakdown by phase

### Sample Chapters
- `sample_chapters/chapter_01.json` - Chapter 1: "Boyhood and Youth"
- `sample_chapters/chapter_07.json` - Chapter 7: "The War of America the Unready"

Each chapter JSON includes:
- Chapter metadata (title, page range, summary)
- Paragraph-level text with unique IDs
- Provenance tracking (scan page references)
- Paragraph type classification (body, footnote, etc.)

### Sample Reading Text
- `sample_reading/full_book_preview.txt` - Preview of TTS-optimized text
- `sample_reading/metadata.json` - Reading format metadata

## Output Schema v2.0

The structure stage generates:

```
structured/
├── metadata.json           # Top-level metadata
├── reading/               # TTS-optimized clean text
│   ├── full_book.txt     # Complete book as clean text
│   ├── page_mapping.json # Scan page → book page mapping
│   └── metadata.json     # Reading metadata
├── data/                 # RAG-ready structured JSON
│   ├── body/            # Chapter files
│   │   ├── chapter_01.json
│   │   ├── chapter_02.json
│   │   └── ...
│   ├── front_matter/    # Preface, introduction, etc.
│   ├── back_matter/     # Appendices, index, etc.
│   ├── document_map.json    # Document structure
│   └── page_mapping.json    # Page mapping
└── archive/             # Legacy formats (if enabled)
```

## Key Features Demonstrated

### 1. Semantic Structure Extraction
Claude Sonnet 4.5 identifies:
- **11 chapters** with accurate titles and boundaries
- **5 front matter sections** (dedication, preface, etc.)
- **2 back matter sections** (index, notes)
- **267 page numbers** extracted and mapped

### 2. Paragraph-Level Provenance
Every paragraph tracks which scan pages it came from:
```json
{
  "id": "ch01_p001",
  "text": "...",
  "scan_pages": [21],
  "type": "body"
}
```

### 3. Cost Efficiency
Total processing cost: **$3.58** for 433 pages
- Structure extraction: only **$0.49** (0.11¢/page)
- Most cost is OCR correction: $2.77
- Targeted fixes: $0.32

### 4. Multiple Output Formats
- **Reading text**: Clean prose for audiobook generation
- **Structured JSON**: Paragraph-level for RAG/search
- **Page mapping**: Links digital text back to scan pages

## Example Use Cases

### Research & Citation
```python
# Find all mentions of "Cuba" with provenance
for chapter in chapters:
    for para in chapter["paragraphs"]:
        if "Cuba" in para["text"]:
            print(f"Found in scan pages: {para['scan_pages']}")
```

### Audiobook Generation
```bash
# Use the clean reading text for TTS
cat structured/reading/full_book.txt | tts_engine > audiobook.mp3
```

### RAG/Semantic Search
```python
# Chunk at paragraph level with metadata
for chapter in chapters:
    for para in chapter["paragraphs"]:
        embed(para["text"], metadata={
            "chapter": chapter["title"],
            "pages": para["scan_pages"],
            "id": para["id"]
        })
```

## Processing Details

**Models:**
- OCR: Tesseract (free)
- Correction: `openai/gpt-4o-mini` via OpenRouter
- Fix: `anthropic/claude-sonnet-4.5` via OpenRouter
- Structure: `anthropic/claude-sonnet-4.5` via OpenRouter

**Duration:** 18 minutes end-to-end

**Parallelization:**
- OCR: Sequential (layout-aware)
- Correction: 30 workers (parallel)
- Fix: 10 workers (parallel)
- Structure: Single-pass (fast enough)

---

**Built with Claude Sonnet 4.5** for intelligent semantic extraction.
