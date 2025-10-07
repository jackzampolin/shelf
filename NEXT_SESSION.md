# Session Handoff: Test Coverage Improvements (Continued)

**Session**: 3 (Part 2) → Session 4
**Date**: October 2025
**Status**: In Progress - Paused for handoff

---

## What We Accomplished This Session

### ✅ Completed

1. **Fixed Import Errors**
   - Consolidated `utils.py` into `utils/__init__.py` package
   - Fixed test_cost_tracking.py import error
   - Removed deprecated files (utils.py, pipeline/structure/generator.py)
   - All 6 cost tracking tests now working

2. **Added OCR Stage Tests**
   - Created `tests/test_ocr_stage.py` with 20 comprehensive tests
   - Tested BlockClassifier, ImageDetector, LayoutAnalyzer
   - All 20 tests passing (100% success rate)
   - Zero API costs (pure Python logic tests)

3. **Updated Documentation**
   - Updated `tests/TEST_COVERAGE.md` with current stats
   - Test count: 99 → 112 tests (+13 net)
   - Test Quality Score: 8/10 → 8.5/10

### 📊 Current Test Coverage

| Component | Tests | Status |
|-----------|-------|--------|
| Checkpoint System | 25 | ✅ Comprehensive |
| Library Management | 25 | ✅ Comprehensive |
| Parallel Processing | 6 | ✅ Good |
| Cost Tracking | 6 | ✅ Fixed |
| Pipeline E2E | 6 | ✅ Good |
| Pipeline Restart | 7 | ✅ Good |
| Structure Phase 1 | 5 | ✅ Good |
| Structure Phase 2 | 17 | ✅ Comprehensive |
| **OCR Stage** | **20** | **✅ New!** |
| **Correct Stage** | **0** | **❌ Next** |
| **Fix Stage** | **0** | **❌ Next** |

---

## Next Session Tasks

### 🎯 Primary Goal: Complete Pipeline Stage Test Coverage

Add unit tests for the remaining two pipeline stages:

#### 1. Correct Stage Tests (Priority 1)
**File to create**: `tests/test_correct_stage.py`

**What to test**:
- LLM correction logic patterns
- Error detection and fixing
- Word-by-word comparison
- Parallel processing of pages
- Checkpoint integration
- Metadata tracking (errors found, fixes applied)

**Reference implementation**: `pipeline/correct.py`

**Approach**:
```python
# Test components:
- ErrorDetector (finds OCR errors)
- CorrectionApplier (applies fixes)
- PageCorrector (main orchestrator)
- Checkpoint handling
- Metadata generation
```

**Estimated tests**: 15-20 tests
**API costs**: None (mock LLM responses)

#### 2. Fix Stage Tests (Priority 2)
**File to create**: `tests/test_fix_stage.py`

**What to test**:
- Agent 4 targeted fix logic
- Pattern recognition for common errors
- Selective page fixing (not all pages)
- Integration with correct stage output
- Cost tracking (minimal API calls)

**Reference implementation**: `pipeline/fix.py`

**Approach**:
```python
# Test components:
- FixPatternDetector (identifies fixable patterns)
- Agent4Fixer (applies targeted fixes)
- PageSelector (determines which pages need fixing)
```

**Estimated tests**: 10-15 tests
**API costs**: None (mock Agent 4 responses)

#### 3. Run Full Test Suite
Once both test files are created:
```bash
uv run python -m pytest tests/ -v --tb=short
```

Expected: ~140+ tests, all passing

#### 4. Update Documentation
- Update `tests/TEST_COVERAGE.md` with final numbers
- Update Test Quality Score (target: 9/10)
- Mark Correct and Fix stages as ✅ Comprehensive

---

## How to Continue

### Step 1: Review Current Code

First, understand what needs to be tested:

```bash
# Check Correct stage implementation
cat pipeline/correct.py | head -100

# Check Fix stage implementation
cat pipeline/fix.py | head -100

# Review existing test patterns
cat tests/test_ocr_stage.py | head -50
```

### Step 2: Create Test Files

Follow the pattern from `test_ocr_stage.py`:
- Use class-based organization (TestCorrector, TestErrorDetector, etc.)
- Include docstrings explaining what each test validates
- Use pytest fixtures for setup/teardown
- Mock LLM calls to avoid API costs
- Test both success and error paths

### Step 3: Iterate Until Passing

```bash
# Run tests as you write them
uv run python -m pytest tests/test_correct_stage.py -v

# Fix failures
# Add more tests
# Repeat
```

### Step 4: Commit and Update Docs

```bash
git add tests/test_correct_stage.py tests/test_fix_stage.py tests/TEST_COVERAGE.md
git commit -m "test: add Correct and Fix stage tests"
```

---

## Testing Patterns to Follow

### ✅ Good Test Patterns (from OCR tests)

1. **Test Components in Isolation**
   ```python
   def test_classifier_header():
       result = BlockClassifier.classify(bbox, text, width, height)
       assert result == "header"
   ```

2. **Test Output Format**
   ```python
   def test_page_json_structure():
       assert 'page_number' in output
       assert 'regions' in output
   ```

3. **Test Error Handling**
   ```python
   def test_handles_missing_file():
       # Verify graceful handling
       assert processor.handle_missing() is not None
   ```

4. **Test Integration**
   ```python
   def test_full_pipeline_flow():
       result = processor.process(input_data)
       assert result['status'] == 'success'
   ```

### ❌ Avoid

- Don't make real API calls (use mocks)
- Don't test implementation details (test behavior)
- Don't write flaky tests (use deterministic inputs)
- Don't skip docstrings

---

## Reference Files

**Test examples**:
- `tests/test_ocr_stage.py` - 20 tests, all passing
- `tests/test_structure_assembly.py` - 17 tests, integration examples
- `tests/test_checkpoint.py` - 25 tests, mocking examples

**Implementation to test**:
- `pipeline/correct.py` - Correct stage
- `pipeline/fix.py` - Fix stage
- `pipeline/run.py` - Pipeline orchestrator

**Documentation**:
- `tests/TEST_COVERAGE.md` - Current coverage report
- `CLAUDE.md` - Project workflow guide
- `STRUCTURE_MIGRATION_PLAN.md` - Architecture docs

---

## Success Criteria

**Session 4 Complete When**:
- ✅ `test_correct_stage.py` created with 15-20 tests
- ✅ `test_fix_stage.py` created with 10-15 tests
- ✅ All tests passing (`pytest tests/ -v`)
- ✅ Total test count: ~140+ tests
- ✅ Test Quality Score: 9/10
- ✅ `TEST_COVERAGE.md` updated
- ✅ All changes committed

**Estimated Time**: 2-3 hours

---

## Quick Start Command

```bash
# Jump right in with this prompt:
"Continue test coverage improvements from Session 3.
Add unit tests for Correct and Fix pipeline stages.
Follow patterns from tests/test_ocr_stage.py.
Reference: NEXT_SESSION.md for details."
```

---

## Questions to Consider

1. Should we mock LLM responses or use fixtures?
   - **Recommendation**: Use fixtures with saved LLM responses

2. How to test parallel processing without actual API calls?
   - **Recommendation**: Test ParallelProcessor separately, mock worker function

3. Should we test checkpoint integration in stage tests?
   - **Recommendation**: Yes, basic save/load validation

---

## Notes

- All tests should run quickly (<1 second per test)
- Zero API costs for unit tests
- Mark any API-calling tests with `@pytest.mark.api`
- Update todo list in test files as you go

---

**Ready to continue? Use the Quick Start Command above!**
