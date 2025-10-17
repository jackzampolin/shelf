# Next Session: Test Stage 3 (Label) Refactor

## ✅ Refactoring Complete!

Stage 3 (Label) has been fully refactored to match Stage 2's gold standard patterns.

**Final Results:**
- `pipeline/3_label/__init__.py`: 464 lines (down from 827, **-363 lines / -44%**)
- `pipeline/3_label/prompts.py`: ~229 lines (new file)
- **Total:** ~693 lines (better organized than original 827)

---

## Completed Commits (1-7)

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

**Commit 7:** Final cleanup (527 → 464 lines, -63)
- Removed clean_stage() method - use inherited StageView.clean_stage()
- Removed unused CheckpointManager import
- All Stage 2 patterns applied

**Total Progress:** 827 → 464 lines (**-363 lines / -44% reduction!**)

---

## All Stage 2 Patterns Applied ✅

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
- ✅ Inherited clean_stage() from base class

---

## Testing Required

**Before merging to main, run full test suite:**

```bash
# 1. Syntax check
python3 -m py_compile pipeline/3_label/__init__.py

# 2. Import test
uv run python -c "import importlib; mod = importlib.import_module('pipeline.3_label'); print('OK')"

# 3. Clean test (inherited from base class)
uv run python ar.py process clean label accidental-president

# 4. Full book test (from scratch)
uv run python ar.py process label accidental-president

# 5. Resume test
# Interrupt the process (Ctrl+C) after a few pages
uv run python ar.py process label accidental-president --resume

# 6. Verify outputs
ls -lh ~/Documents/book_scans/accidental-president/labels/
```

---

## Success Criteria

- [ ] All syntax/import tests pass
- [ ] Label stage completes on test book
- [ ] Output JSON matches pre-refactor format
- [ ] Checkpoint resume works correctly
- [ ] Cost tracking accurate
- [ ] Progress bar shows real-time updates
- [ ] Clean command works (inherited from base class)
- [ ] Code reduced by 44% (827 → 464 lines)
- [ ] All Stage 2 patterns applied

---

## Next Steps After Testing

1. **Test on full book:** Run label stage on `accidental-president`
2. **Verify output quality:** Compare with pre-refactor outputs
3. **Test checkpoint resume:** Ensure resume works correctly
4. **Test clean command:** Verify inherited clean_stage() works
5. **Update Issue #60:** Mark Label stage refactor complete
6. **Move to next stage:** Start refactoring Stage 4 (Merge) if Label tests pass

---

## Notes

- **Refactoring complete!** All 7 commits done
- **Stage 3 now matches Stage 2 quality** - same patterns, same structure
- **44% code reduction** - more maintainable and consistent
- **Ready for testing** - full validation required before merge
- **Total estimated time:** ~30 minutes for testing

---

## Reference

**Architecture & Principles:** See [Issue #56](https://github.com/jackzampolin/scanshelf/issues/56)
**Production Patterns:** `docs/standards/` directory
**Test Book:** `accidental-president` (small book for testing)
