# OCR Rebuild Plan

## Status: Ready to execute

### What Changed
Multi-PSM OCR with vision-based selection is now implemented:
- Runs PSM 3, 4, 6 in parallel
- Vision LLM selects best PSM per page
- New structure: `ocr/psm{N}/page_*.json`
- Downstream stages need updating to read from PSM directories

### The Plan

**1. Clean rebuild (while on a hike ☕🚶)**
```bash
# Turn on caffeine (prevent sleep)
# Then:
uv run python shelf.py sweep ocr --clean
```

**Expected duration:** Several hours (19 books, ~9000 pages total)
- PSM extraction: ~2-3 min per book (parallel CPU)
- Vision selection: ~1-2 min per book (LLM calls)

**2. When back from hike**

Check results:
```bash
uv run python shelf.py sweep reports --stage-filter ocr
```

Should show:
- All 19 books with OCR complete
- PSM completion: 100% for psm3, psm4, psm6
- Vision selection: 100%
- `ocr/psm_selection.json` created for each book

**3. Next: Update downstream stages**

Downstream stages need to read from selected PSM:

```python
# Old (correction, label, merge):
ocr_data = storage.stage('ocr').load_page(page_num)

# New (needs implementation):
# 1. Load psm_selection.json
# 2. Read from ocr/psm{selected}/page_*.json
```

**Files to update:**
- `pipeline/correct.py` - reads OCR output
- `pipeline/label.py` - reads OCR output
- `pipeline/merge.py` - merges OCR + corrected + labeled

**Strategy:** Add helper method to BookStorage:
```python
def load_selected_ocr(page_num: int) -> OCRPageOutput:
    """Load OCR output from winning PSM."""
    selection = self.load_psm_selection()
    psm = selection[str(page_num)]['selected_psm']
    return self.stage('ocr').load_page_from_psm(page_num, psm)
```

## Progress Tracking

- [x] Multi-PSM OCR implemented
- [x] Vision selection implemented
- [x] Checkpoint consolidation
- [x] Module extraction
- [x] Clean code review
- [ ] Clean rebuild (in progress)
- [ ] Update correction stage
- [ ] Update label stage
- [ ] Update merge stage
- [ ] Re-run correction sweep
- [ ] Re-run label sweep
- [ ] Re-run merge sweep
- [ ] Verify output quality

## Cost Estimate

**OCR Stage:**
- PSM extraction: Free (Tesseract)
- Vision selection: ~$0.05 per page × 9000 pages = **~$450**

**Full rebuild (OCR + correction + label + merge):**
- Estimate: **~$900-1200 total**

Worth it for:
- Better OCR quality (3 PSMs → best selected)
- Infrastructure improvements (sub-stage tracking)
- Cleaner codebase
