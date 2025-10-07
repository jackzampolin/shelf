# Test Strategy: Unit vs Integration

**Goal**: Fast unit tests with committed fixtures + comprehensive integration tests with full book

---

## Test Categories

### Unit Tests (`@pytest.mark.unit`)
- **Data**: Committed fixtures only (tests/fixtures/roosevelt/)
- **Speed**: Fast (<5 seconds)
- **API Calls**: No (or minimal mocked)
- **Run**: Always (CI, pre-commit, development)
- **Coverage**: Core logic, edge cases, error handling

### Integration Tests (`@pytest.mark.integration`)
- **Data**: Full Roosevelt book (~/Documents/book_scans/roosevelt-autobiography)
- **Speed**: Slower (10s - 2min)
- **API Calls**: Optional (some tests may make real calls)
- **Run**: On-demand (before releases, validation)
- **Coverage**: End-to-end workflows, real data validation

### API Tests (`@pytest.mark.api`)
- **Data**: Either committed or full book
- **Speed**: Depends on API latency
- **API Calls**: Yes (real OpenRouter calls, ~$0.10/run)
- **Run**: Selective (before deployments)
- **Coverage**: LLM integration, prompt validation

---

## Committed Fixtures

**Location**: `tests/fixtures/roosevelt/`

**Contents** (target: ~200KB total):

```
roosevelt/
├── metadata.json              # Book metadata
├── ocr/                       # 5 pages
│   ├── page_0010.json
│   ├── page_0050.json
│   ├── page_0100.json
│   ├── page_0200.json
│   └── page_0500.json
├── corrected/                 # 5 pages (same)
│   └── ...
├── needs_review/              # 3 sample review pages
│   ├── page_0015.json        # Early book
│   ├── page_0250.json        # Mid book
│   └── page_0475.json        # Late book
├── structured/
│   ├── metadata.json         # Structure metadata
│   ├── extraction/           # Sample extraction data
│   │   ├── chapters.json     # Chapter boundaries
│   │   ├── footnotes.json    # Footnotes sample
│   │   └── bibliography.json # Bib sample
│   └── reading/              # Sample chapter/chunk
│       ├── chapter_05.json
│       └── chunk_025.json
```

**Size**: ~200KB (acceptable for git)

---

## Test Execution Patterns

```bash
# Fast unit tests (default for CI)
pytest -m unit -v

# Integration tests (requires full book)
pytest -m integration -v

# All tests except API
pytest -m "not api" -v

# Only API tests
pytest -m api -v

# Everything
pytest -v

# Fast + API (skip integration)
pytest -m "unit or api" -v
```

---

## Fixture Usage by Test Type

### Unit Tests
```python
@pytest.mark.unit
def test_ocr_extraction(roosevelt_fixtures):
    """Fast test using committed fixtures."""
    page = load_page(roosevelt_fixtures / "ocr" / "page_0010.json")
    assert page['text']
```

### Integration Tests
```python
@pytest.mark.integration
def test_full_pipeline(roosevelt_full_book):
    """Integration test requiring full book."""
    if roosevelt_full_book is None:
        pytest.skip("Full Roosevelt book required")

    # Test full pipeline on real data
    ...
```

### API Tests (can be either)
```python
@pytest.mark.api
@pytest.mark.unit
def test_llm_correction(roosevelt_fixtures):
    """API test using small committed fixture."""
    # Makes real API call but only on 1 page
    ...
```

---

## Migration Plan

### Phase 1: Extract Fixtures ✅
- [x] Basic fixtures (5 OCR + 5 corrected pages)
- [ ] Add 3 needs_review/ samples
- [ ] Add structured/extraction/ samples
- [ ] Add 1 chapter + 1 chunk sample

### Phase 2: Add Markers
- [ ] Update pytest.ini with markers
- [ ] Add markers to all test files
- [ ] Document marker usage in TEST_STRATEGY.md

### Phase 3: Update Tests
- [ ] Remove hardcoded paths
- [ ] Use roosevelt_fixtures for unit tests
- [ ] Use roosevelt_full_book for integration tests
- [ ] Replace skip calls with proper fixture checks

### Phase 4: CI Integration
- [ ] Run unit tests on every push
- [ ] Run integration tests on PR to main
- [ ] Run API tests manually before releases

---

## Success Criteria

**Unit Tests**:
- ✅ Run in <10 seconds
- ✅ Work on fresh clone (no setup)
- ✅ Cover 80%+ of core logic
- ✅ No external dependencies

**Integration Tests**:
- ✅ Validate full pipeline
- ✅ Catch real-world issues
- ✅ Run on-demand
- ✅ Clear skip messages if data missing

**Combined**:
- ✅ 149 tests total
- ✅ 9.5/10 quality score maintained
- ✅ Clear execution patterns
- ✅ Fast feedback loop

---

## Example Test File Structure

```python
"""Test correct stage with unit and integration tests."""

import pytest

# ============================================================================
# UNIT TESTS - Fast, committed fixtures only
# ============================================================================

@pytest.mark.unit
def test_detect_errors(roosevelt_fixtures):
    """Unit test: Error detection logic."""
    page = load_page(roosevelt_fixtures / "ocr" / "page_0010.json")
    errors = detect_errors(page['text'])
    assert len(errors) > 0

@pytest.mark.unit
@pytest.mark.api
def test_correct_single_page(roosevelt_fixtures):
    """Unit test with API: Correct 1 page."""
    # Fast API test on single committed page
    ...

# ============================================================================
# INTEGRATION TESTS - Full book required
# ============================================================================

@pytest.mark.integration
def test_correct_full_book(roosevelt_full_book):
    """Integration test: Full book correction."""
    if roosevelt_full_book is None:
        pytest.skip("Full Roosevelt book required for integration test")

    # Test on real 638-page book
    ...

@pytest.mark.integration
@pytest.mark.api
def test_parallel_correction(roosevelt_full_book):
    """Integration + API: Parallel correction on full book."""
    if roosevelt_full_book is None:
        pytest.skip("Full Roosevelt book required")

    # Test parallel processing with real API calls
    ...
```

---

**Status**: Design Complete
**Next**: Extract additional fixtures, add markers to pytest.ini
