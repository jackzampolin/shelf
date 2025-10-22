# Test Fixtures: Accidental President

Real book data extracted from pages 5-15 of "The Accidental President" by A.J. Baime.

## Contents

- **metadata.json**: Book metadata
- **ocr/**: 11 OCR output files (pages renumbered 1-11)
- **source/**: 11 source page images (600 DPI PNG, pages renumbered 1-11)

## Original Pages

These fixtures correspond to:
- Original PDF pages: 5-15
- Renumbered for testing: 1-11

## Usage

Used by `tests/pipeline/test_correction_integration.py` for integration testing
the correction stage with real book data and actual LLM API calls.

## Running Tests

```bash
# Skip integration tests (default - no API key needed)
pytest tests/pipeline/test_correction_integration.py -v

# Run integration tests (requires OPENROUTER_API_KEY)
OPENROUTER_API_KEY=your_key pytest tests/pipeline/test_correction_integration.py -v -s -m integration
```

## File Sizes

- Total OCR data: ~55KB (JSON)
- Total source images: ~3.5MB (PNG at 600 DPI)
