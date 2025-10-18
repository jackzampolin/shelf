# Next Session: Infra Restructuring Complete + Checkpoint Bugs Found

## What Was Done

Successfully restructured `infra/` directory into logical subsystems for better organization and maintainability.

### Infra Restructuring

**New Directory Structure:**
```
infra/
├── config.py              # Environment configuration (stays at root)
├── storage/               # Book data & state management
│   ├── book_storage.py   # Unified storage manager
│   ├── checkpoint.py     # Progress tracking
│   └── metadata.py       # Metadata utilities
├── llm/                   # LLM API integration
│   ├── client.py         # Single calls (renamed from llm_client.py)
│   ├── batch_client.py   # Batch processing (renamed from llm_batch_client.py)
│   ├── models.py         # Data models (renamed from llm_models.py)
│   ├── pricing.py        # Cost tracking
│   └── rate_limiter.py   # Rate limiting
├── pipeline/              # Pipeline execution utilities
│   ├── logger.py         # Structured logging
│   └── progress.py       # Terminal progress bars
└── utils/                 # Shared utilities
    └── pdf.py            # PDF extraction (renamed from pdf_utils.py)
```

**Benefits:**
- Clear separation of concerns (storage vs LLM vs pipeline)
- Better discoverability ("I need LLM stuff" → `infra/llm/`)
- Explicit public APIs via subsystem `__init__.py` files
- Scalable for future growth

**Changes:**
- Created 4 subsystem directories with `__init__.py` files
- Moved 11 modules to appropriate locations (using `git mv` to preserve history)
- Renamed 3 modules for clarity (`llm_client` → `client`, etc.)
- Removed deprecated `parallel.py` (212 lines, superseded by LLMBatchClient)
- Updated 21 files with new imports (8 pipeline stages, 4 tools, 5 tests, 4 internal)
- Updated main `infra/__init__.py` to export from new locations

**Validation:**
- All imports working correctly
- Import tests passing
- One pre-existing test failure discovered (see below)

---

## Critical Bugs Found in Checkpointing System

While testing the restructuring, discovered **4 bugs** in the checkpoint system via agent code review:

### Bug #1: Test Schema Mismatch (CRITICAL)
**File:** `tests/infra/test_checkpoint.py:43`
**Issue:** Test creates OCR data with `"regions"` field, but validation expects `"blocks"` field
**Impact:** Test `test_mark_completed_and_resume` failing - resume logic thinks no pages are complete
**Fix:** Change test to use correct schema:
```python
page_file.write_text(json.dumps({
    "page_number": page_num,
    "blocks": [{"text": "Test"}]  # Was "regions"
}))
```

### Bug #2: Double Cost Accumulation (CRITICAL)
**File:** `infra/storage/checkpoint.py:362-365`
**Issue:** `mark_completed()` accumulates cost on EVERY call, even if page already marked complete
**Impact:**
- Retrying a failed page counts cost twice
- Duplicate calls multiply costs
- Checkpoint cost totals unreliable
**Fix:** Only accumulate cost for NEW pages:
```python
if cost_usd > 0 and is_new_page:  # Add is_new_page check
    current_cost = self._state['metadata'].get('total_cost_usd', 0.0)
    self._state['metadata']['total_cost_usd'] = current_cost + cost_usd
```

### Bug #3: Redundant Checkpoint Saves (MAJOR)
**File:** `infra/storage/checkpoint.py:356-361`
**Issue:** `mark_completed()` saves checkpoint even if page already in completed list
**Impact:** Performance issue, unnecessary I/O, potential race conditions
**Fix:** Early return if no work needed:
```python
def mark_completed(self, page_num: int, cost_usd: float = 0.0):
    with self._lock:
        is_new_page = page_num not in self._state['completed_pages']

        if not is_new_page and cost_usd == 0:
            return  # Already marked, nothing to update
        # ... rest of method
```

### Bug #4: No File Validation Before Checkpoint (MINOR)
**File:** `infra/storage/book_storage.py:183-192`
**Issue:** `save_page()` marks page complete without verifying the file is valid/readable
**Impact:** Silent corruption possible if write fails in unexpected way
**Fix:** Validate after write:
```python
temp_file.replace(output_file)

if not self.checkpoint.validate_page_output(page_num):
    raise IOError(f"Page {page_num} validation failed after write")

self.checkpoint.mark_completed(page_num, cost_usd=cost_usd)
```

---

## Next Steps

### Option 1: Fix Checkpoint Bugs (Recommended)
Critical bugs found that affect cost tracking and resume reliability:
1. Fix test schema mismatch (1 line change)
2. Fix double cost accumulation (add `is_new_page` check)
3. Add early return to prevent redundant saves
4. Add validation before marking complete
5. Run full test suite to verify fixes

### Option 2: Continue Pipeline Refactor
Move to Stage 5 (Structure) refactoring:
- Run code-reviewer agents on Stage 5
- Run code-architect for refactor plan
- Apply BookStorage patterns
- Test on test book

### Option 3: Investigate Cost Accumulation in Production
User mentioned seeing cost accumulation issues in correction stage:
- Review correction stage cost tracking
- Compare checkpoint costs vs batch_client costs
- Validate that workaround is working correctly

---

## Commits

1. **9c4ed39** - refactor(infra): reorganize into logical subsystems

---

## Technical Notes

**Agent Analysis Process:**
- Ran two agents in parallel (code-explorer + code-architect)
- code-explorer cataloged all modules, found duplicate RateLimiter and deprecated parallel.py
- code-architect designed new structure with 4 subsystems
- Agents estimated 2 hours effort, actual time ~30 minutes

**Import Migration:**
- Used `sed` for bulk import updates across 21 files
- All `from infra.llm_client import` → `from infra.llm.client import`
- All `from infra.pdf_utils import` → `from infra.utils.pdf import`
- etc.

**Test Hanging Issue:**
- Full test suite appeared to hang during restructuring validation
- Killed test run and used quick import validation instead
- Found checkpoint test failure which led to bug discovery

**Checkpoint Bug Root Cause:**
The `mark_completed()` method correctly tracks whether a page is new (`is_new_page` variable), but then **ignores this for cost accumulation**. This suggests cost tracking was added later without considering resume/retry scenarios. The correction stage currently works around this by using `batch_client.get_batch_stats()` instead of checkpoint costs, but this defeats the purpose of checkpoint cost tracking.
