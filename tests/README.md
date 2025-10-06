# Scanshelf Test Suite

Comprehensive end-to-end tests for the book processing pipeline.

## Philosophy: No Mocks

These tests use **real functionality with no mocks**:
- ✅ Real API calls (OpenRouter, OpenAI, Anthropic)
- ✅ Real OCR processing (Tesseract)
- ✅ Real file system operations
- ✅ Real cost tracking (small amounts)

**Why?** Unit tests with mocks often give false confidence. We test the actual system behavior to catch real regressions.

## Cost Per Test Run

Running the full test suite costs approximately **$0.10-0.15**:
- OCR: Free (Tesseract)
- Correction: ~$0.05-0.08 (gpt-4o-mini on 5 pages × multiple tests)
- Structure: ~$0.03-0.05 (Claude Sonnet on 5 pages × multiple tests)

This is cheap enough to run frequently during development.

## Running Tests

### Run All Tests

```bash
# From project root
uv run pytest

# Or with activated venv
pytest
```

### Run Specific Test Files

```bash
# End-to-end pipeline tests
uv run pytest tests/test_pipeline_e2e.py

# Pipeline restart tests
uv run pytest tests/test_restart.py

# Library/catalog tests
uv run pytest tests/test_library.py

# Cost tracking tests
uv run pytest tests/test_cost_tracking.py
```

### Run by Marker

```bash
# Only end-to-end tests
uv run pytest -m e2e

# Only tests that make API calls
uv run pytest -m api

# Only slow tests (>30 seconds)
uv run pytest -m slow

# Skip slow tests
uv run pytest -m "not slow"
```

### Run Specific Test

```bash
uv run pytest tests/test_pipeline_e2e.py::test_full_pipeline_ocr_to_structure
```

### Verbose Output

```bash
# See detailed output
uv run pytest -v

# See print statements
uv run pytest -s

# Both
uv run pytest -vs
```

## Test Structure

```
tests/
├── README.md                    # This file
├── fixtures/                    # Test data
│   ├── README.md               # Fixture documentation
│   ├── extract_test_pages.py  # Fixture generation script
│   └── test_book/              # 5-page test book
│       ├── metadata.json
│       └── source/pdfs/        # Individual page PDFs
├── test_pipeline_e2e.py        # Full pipeline tests
├── test_restart.py             # Pipeline restart tests
├── test_library.py             # Library/catalog tests
└── test_cost_tracking.py       # Cost tracking tests
```

## Test Fixtures

The `fixtures/test_book/` directory contains a 5-page sample from *The Accidental President*:

- **Page 1**: Title page (easy - baseline)
- **Page 5**: Very challenging (0.00 confidence in real processing)
- **Page 109**: Hard (0.60 confidence, 5 OCR errors)
- **Page 200**: Mid-book (normal difficulty)
- **Page 384**: Hard (0.80 confidence, 6 OCR errors)

These pages are committed to git (~50KB total) for reproducible tests.

### Regenerating Fixtures

If you need fresh fixtures:

```bash
uv run python tests/fixtures/extract_test_pages.py
```

This extracts from `~/Documents/book_scans/modest-lovelace/source/pdfs/`.

## Test Categories

### End-to-End Tests (`test_pipeline_e2e.py`)

Tests the complete pipeline flow:
- ✅ Full pipeline: OCR → Correct → Fix → Structure
- ✅ Error handling on difficult pages
- ✅ Valid JSON output verification
- ✅ Text quality spot checks

**Markers**: `@pytest.mark.e2e`, `@pytest.mark.api`, `@pytest.mark.slow`

### Restart Tests (`test_restart.py`)

Tests pipeline restart capabilities:
- ✅ Restart from correction stage
- ✅ Restart from structure stage
- ✅ Run specific stages only
- ✅ Idempotent reruns
- ✅ Fix stage skipping logic

**Markers**: `@pytest.mark.e2e`, `@pytest.mark.api`

### Library Tests (`test_library.py`)

Tests catalog management:
- ✅ Add books to library
- ✅ Update scan metadata
- ✅ Query books and scans
- ✅ Statistics aggregation
- ✅ Sync from metadata.json
- ✅ Persistence to disk

**Markers**: `@pytest.mark.filesystem`

### Cost Tracking Tests (`test_cost_tracking.py`)

Tests cost tracking accuracy:
- ✅ Costs recorded per stage
- ✅ Total cost calculation
- ✅ Library sync of costs
- ✅ Cost breakdown by stage
- ✅ Rerun cost tracking

**Markers**: `@pytest.mark.e2e`, `@pytest.mark.api`

## What Tests Verify

### Pipeline Completion
- All stages complete successfully
- No crashes or exceptions
- Graceful handling of difficult pages

### File Outputs
- Expected directories and files exist
- JSON files are valid and parseable
- Markdown outputs are generated
- Metadata tracking is complete

### Cost Tracking
- Each stage records cost_usd
- Costs sync to library.json
- Total costs are reasonable
- Cost breakdown is available

### Data Integrity
- Processing history is maintained
- Metadata is consistent
- Library catalog stays synced
- No data loss on reruns

### Quality
- Corrected text is substantially better than raw OCR
- Common words appear correctly
- Structure detection works (chapters, chunks)
- Text is not gibberish

## Continuous Integration

Currently tests run **locally** before commits. In the future, could add GitHub Actions:

```yaml
# .github/workflows/tests.yml (example)
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - run: uv pip install -e .
      - run: uv run pytest -m "not slow"  # Skip slow tests in CI
    env:
      OPEN_ROUTER_API_KEY: ${{ secrets.OPEN_ROUTER_API_KEY }}
```

## Debugging Failed Tests

### Check Test Logs

```bash
# Tests write to tests/test.log
cat tests/test.log
```

### Run Single Test with Verbose Output

```bash
uv run pytest tests/test_pipeline_e2e.py::test_full_pipeline_ocr_to_structure -vs
```

### Inspect Test Artifacts

Tests use `tmp_path` fixtures - artifacts are in `/tmp/pytest-of-<user>/`:

```bash
# Find recent test runs
ls -lt /tmp/pytest-of-$USER/ | head
```

### Check API Costs

If tests fail due to API costs, check your OpenRouter dashboard:
https://openrouter.ai/activity

## Adding New Tests

When adding new tests:

1. **Follow the no-mocks philosophy** - Test real behavior
2. **Use fixtures** - Leverage `test_book_dir` and `test_library` fixtures
3. **Add appropriate markers** - Use `@pytest.mark.e2e`, `@pytest.mark.api`, etc.
4. **Keep tests focused** - One concept per test function
5. **Assert meaningfully** - Check actual behavior, not just "no crash"

Example:

```python
@pytest.mark.e2e
@pytest.mark.api
def test_my_new_feature(test_book_dir, test_library):
    """
    Test that new feature works correctly.

    Describe what you're testing and why.
    """
    # Setup
    scan_id = "test-new-feature"
    book_dir = test_library.storage_root / scan_id
    shutil.copytree(test_book_dir, book_dir)

    # Execute
    result = do_something(book_dir)

    # Assert
    assert result.success, "Feature should work"
    assert result.output_file.exists(), "Should create output"
```

## See Also

- [fixtures/README.md](fixtures/README.md) - Test fixture documentation
- [../CLAUDE.md](../CLAUDE.md) - AI assistant workflow guide
- [../README.md](../README.md) - Project documentation
