# Test Fixtures

This directory contains test data for the Scanshelf pipeline.

## test_book/

A 5-page sample extracted from `modest-lovelace` (The Accidental President).

**Test Pages:**
- **Page 1**: Title page (easy - baseline)
- **Page 5**: Very challenging (0.00 confidence in real processing)
- **Page 109**: Hard (0.60 confidence, 5 OCR errors)
- **Page 200**: Mid-book (normal difficulty)
- **Page 384**: Hard (0.80 confidence, 6 OCR errors)

**Structure:**
```
test_book/
├── metadata.json       # Book metadata
└── source/
    └── pdfs/          # Individual page PDFs
        ├── page_0001.pdf
        ├── page_0005.pdf
        ├── page_0109.pdf
        ├── page_0200.pdf
        └── page_0384.pdf
```

## Regenerating Fixtures

If you need to regenerate the test pages:

```bash
uv run python tests/fixtures/extract_test_pages.py
```

This will extract fresh copies from `~/Documents/book_scans/modest-lovelace/source/pdfs/`.

## Using in Tests

Tests should treat `test_book` like any other book scan:

```python
def test_full_pipeline():
    # Copy test_book to temp directory
    # Run: OCR → Correct → Fix → Structure
    # Verify outputs and costs
```

## Cost Estimate

Running the full pipeline on these 5 pages:
- OCR: Free (Tesseract)
- Correct: ~$0.01 (gpt-4o-mini)
- Fix: ~$0.005 (if needed)
- Structure: ~$0.01 (Claude Sonnet)
- **Total: ~$0.025 per test run**

This is cheap enough to run frequently without worry.

## Committed to Git

These fixtures are committed to git to ensure:
- Reproducible tests across machines
- No dependency on live data
- Fast test startup (no generation needed)
- Consistent test results

The total size is ~50KB (5 single-page PDFs).
