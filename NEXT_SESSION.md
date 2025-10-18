# Next Session: Refactor Stage 1 (OCR) to Match Stages 2-3

## Overview

Stage 1 (OCR) needs refactoring to match the gold standard patterns established in Stages 2 (Correction) and 3 (Label). Since OCR doesn't use LLM calls, it's a more straightforward refactor focused on:
- BookStorage APIs for file operations
- Checkpoint property pattern
- No manual stats tracking
- Clean code structure

## Pre-Refactor Analysis Plan

Before starting the refactor, we need to understand current best practices and the OCR stage's current state.

### Step 1: Review Stage 2 Best Practices

Run code-reviewer agent on Stage 2 (Correction) to document current best practices:

```bash
# This will establish our gold standard patterns
```

**Agent Task:**
Review `pipeline/2_correction/__init__.py` to document:
- BookStorage API usage patterns
- Checkpoint property pattern
- Progress tracking patterns
- Error handling patterns
- File I/O patterns
- Stats tracking approach
- Clean code structure

**Expected Output:** Comprehensive documentation of Stage 2 patterns to use as reference.

---

### Step 2: Review Current OCR Stage

Run code-reviewer agent on Stage 1 (OCR) to assess current state:

```bash
# This will identify what needs to change
```

**Agent Task:**
Review `pipeline/1_ocr/__init__.py` to identify:
- Current file access patterns (manual vs BookStorage)
- Current checkpoint usage (manual vs property)
- Current stats tracking approach
- Any manual path construction
- Any patterns that don't match Stages 2-3
- Code complexity and organization

**Expected Output:** Gap analysis between current OCR and Stage 2 patterns.

---

### Step 3: Architecture Design

Run architect agent to design the refactoring approach:

**Agent Task:**
Based on the gap analysis, design the refactoring plan:
1. Identify all changes needed to match Stage 2 patterns
2. Break down into logical commits
3. Estimate line count changes
4. Identify risks and edge cases
5. Suggest testing strategy

**Expected Output:** Detailed refactoring plan with commit-by-commit breakdown.

---

## Current OCR Stage Overview

**File:** `pipeline/1_ocr/__init__.py`
**Current patterns (likely):**
- Manual path construction
- Direct file access (not via BookStorage)
- Manual CheckpointManager instantiation
- Self.stats dict for tracking
- Custom clean_stage() method

**Target patterns (from Stages 2-3):**
- Use `storage.ocr.*` APIs for all file operations
- Use `storage.ocr.checkpoint` property
- No self.stats dict (checkpoint is source of truth)
- Inherited `clean_stage()` from StageView
- Simplified page counting (checkpoint auto-detects)

---

## Key Differences: OCR vs Correction/Label

**OCR stage is simpler:**
- ✅ No LLM calls (no LLMBatchClient needed)
- ✅ No parallel batch processing
- ✅ No callback patterns
- ✅ Simpler I/O (just save OCR output)

**OCR stage is unique:**
- Extracts images from pages (images_dir handling)
- Uses moondream2 API (different from OpenRouter)
- May have different progress tracking needs

---

## Success Criteria

After refactoring, OCR stage should:
- [ ] Use BookStorage APIs exclusively (no manual paths)
- [ ] Use checkpoint property (no manual CheckpointManager)
- [ ] No self.stats dict
- [ ] Inherit clean_stage() from StageView
- [ ] Match Stage 2 code organization
- [ ] Maintain all current functionality
- [ ] Pass all tests on test book

---

## Next Steps

1. **Run Stage 2 review agent** → Document best practices
2. **Run OCR review agent** → Identify gaps
3. **Run architect agent** → Design refactoring plan
4. **Implement refactoring** → Following the plan
5. **Test on test book** → Validate functionality
6. **Update Issue #57** → Mark OCR refactor complete

---

## Reference Materials

**Completed Refactors:**
- Stage 2 (Correction): Gold standard - 461 lines, all patterns applied
- Stage 3 (Label): Just completed - 450 lines, -46% reduction

**Architecture:** [Issue #56](https://github.com/jackzampolin/scanshelf/issues/56)
**Production Patterns:** `docs/standards/` directory
**Test Book:** `accidental-president` (small book for testing)

---

## Notes

- OCR refactor should be simpler than Label (no LLM batch processing)
- Focus on BookStorage APIs and checkpoint property
- Preserve image extraction functionality
- May be able to complete in fewer commits than Label stage
