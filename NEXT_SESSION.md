# Next Session: Complete Stage 3 (Label) Refactoring - Commit 7

## Progress Summary

### ✅ Completed Commits (1-6)

**Commit 1:** Extract prompts to prompts.py (827 → 612 lines, -215)
- Created `pipeline/3_label/prompts.py` with SYSTEM_PROMPT and build_user_prompt
- Simplified OCR formatting using json.dumps() (Stage 2 pattern)
- Removed 4 old prompt methods

**Commit 2:** Use LLMBatchClient imports and schema (612 → 569 lines, -43)
- Replaced LLMClient with LLMBatchClient imports
- Replaced inline JSON schema with LabelPageOutput.model_json_schema()
- Single source of truth for schema

**Commit 3:** Add parallel batch loading (569 → 666 lines, +97)
- Pre-load all pages in parallel before LLM calls
- Build LLMRequest objects during loading
- Separate I/O from API calls

**Commit 4:** Replace manual retry with batch processing (666 → 595 lines, -71)
- Removed manual retry loop
- Added _handle_progress_event() and _handle_result() callbacks
- Batch client handles all retries automatically

**Commit 5:** Migrate to BookStorage APIs (595 → 590 lines, -5)
- storage.label.validate_inputs(), save_page(), update_metadata()
- storage.label.get_log_dir() for batch client logs
- Single source of truth for paths

**Cleanup:** Remove redundant checks (590 → 578 lines, -12)
- Removed duplicate file existence checks
- Trust BookStorage validation

**Commit 6:** Use checkpoint property and remove stats (578 → 527 lines, -51)
- Use storage.label.checkpoint property
- checkpoint.reset(confirm=True) pattern
- Remove self.stats dict (batch_client is source of truth)

**Total Progress:** 827 → 527 lines (**-300 lines, 36% reduction!**)

---

## 🚧 Remaining: Commit 7 - Final Cleanup

**Goal:** Remove clean_stage() and unused imports, final polish

### Tasks for Commit 7

1. **Remove clean_stage() method** (~60 lines)
   - Use inherited `StageView.clean_stage()` from base class
   - No custom implementation needed

2. **Remove unused imports:**
   - `create_logger` (if logger removed)
   - `CheckpointManager` (using checkpoint property now)
   - Any other unused imports

3. **Final cleanup:**
   - Verify all Stage 2 patterns applied
   - Check for any remaining manual path construction
   - Ensure all TODOs addressed

**Expected:** 527 → ~470 lines (-57 lines)

---

## Final Expected State

**Files:**
- `pipeline/3_label/__init__.py`: ~470 lines (down from 827, **-357 lines / -43%**)
- `pipeline/3_label/prompts.py`: ~245 lines (new file)
- **Total:** ~715 lines (better organized than original 827)

**All Stage 2 Patterns Applied:**
- ✅ LLMBatchClient with parallel batch processing
- ✅ Extracted prompts (SYSTEM_PROMPT + build_user_prompt)
- ✅ BookStorage APIs (storage.label.*)
- ✅ Checkpoint property (storage.label.checkpoint)
- ✅ checkpoint.reset(confirm=True) pattern
- ✅ storage.label.save_page() for atomic writes
- ✅ Callback methods (_handle_progress_event, _handle_result)
- ✅ No manual retry logic
- ✅ No self.stats dict
- ✅ Simplified OCR formatting (json.dumps like Stage 2)
- ⏳ Inherited clean_stage() (Commit 7)

---

## Testing Strategy

**After Commit 7:**
```bash
# Syntax check
python3 -m py_compile pipeline/3_label/__init__.py

# Import test
uv run python -c "import importlib; mod = importlib.import_module('pipeline.3_label'); print('OK')"

# Clean test
uv run python ar.py process clean label accidental-president

# Full book test
uv run python ar.py process label accidental-president

# Resume test
uv run python ar.py process label accidental-president --resume
```

---

## Success Criteria

- [ ] All tests pass
- [ ] Label stage completes on test book
- [ ] Output JSON matches pre-refactor format
- [ ] Checkpoint resume works
- [ ] Cost tracking accurate
- [ ] Progress bar shows real-time updates
- [ ] Clean command works (inherited from base class)
- [ ] Code reduced by ~43% (827 → ~470 lines)
- [ ] All Stage 2 patterns applied

---

## Notes

- **Almost done!** Just Commit 7 remaining (final cleanup)
- **Stage 3 matches Stage 2 quality** after this refactor
- **Total estimated time:** ~1 hour for Commit 7
- **Ready to test** on full book after Commit 7
