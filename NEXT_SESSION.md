# Next Session: Stage 2/3 Infrastructure Review + Complete Corrections

**Date:** 2025-10-13
**Branch:** `refactor/pipeline-redesign`
**Status:** Stage 2 (Correction) & Stage 3 (Label) partially complete on 9 books

---

## Current State

### ✅ Completed This Session

1. **Three-Way Merge Implementation**
   - ✅ Fixed Stage 4 (Merge) to properly merge OCR + Correction + Label data
   - ✅ Discovered Stage 2/3 are independent parallel operations (both read from OCR)
   - ✅ Updated merge to read from ALL THREE directories: `ocr/`, `corrected/`, `labels/`
   - ✅ Tested on accidental-president: works correctly

2. **Pipeline Stage Renumbering**
   - ✅ Stage 3: Label (new)
   - ✅ Stage 4: Merge (formerly 3)
   - ✅ Stage 5: Structure (formerly 4)
   - ✅ Updated all imports across codebase
   - ✅ Committed changes

3. **Library List Enhancement**
   - ✅ Fixed `ar library list` to show actual pipeline status
   - ✅ Now displays: `OCR:✅ COR:✅ LAB:✅ MRG:✅ STR:○`
   - ✅ Smart completion detection (shows ✅ even if checkpoint says "in_progress" but all pages done)

4. **Parallel Correction Attempt**
   - ✅ Spawned 9 agents to run correction on all books in parallel
   - ⚠️ Most agents timed out (Task tool ~15min limit)
   - ✅ Only hap-arnold completed (93.8% success, 21 failed pages)
   - ⏳ Other books 64-86% complete (~904 pages remaining)

---

## Critical Issues Discovered

### 🐛 Issue #1: Checkpoint Not Resuming Properly

**Problem:** Running correction without `--resume` flag **resets checkpoint** and starts over.

**Evidence:**
- User restarted china-lobby in terminal, it started from scratch
- Checkpoint logic: `if not resume: self.checkpoint.reset()` (line 113-114 in correction stage)

**Impact:** Wastes money re-processing already-completed pages

**Fix Required:**
- Either make `--resume` the default behavior
- OR add warning when checkpoint exists but not using `--resume`
- OR check if checkpoint exists and prompt user before resetting

---

### 🐛 Issue #2: Stage Status Not Updated to "completed"

**Problem:** hap-arnold shows `COR:⏳` (in_progress) even though all pages are done.

**Evidence:**
```json
{
  "status": "in_progress",
  "total_pages": 340,
  "completed_pages": 340,
  "created_at": "2025-10-13T10:55:31.102927",
  "completed_at": "2025-10-13T11:21:15.420784"
}
```

**Workaround:** Library list now checks if `completed_pages == total_pages` and shows ✅

**Root Cause:** Stage doesn't call `mark_stage_complete()` when all pages done but some failed

**Fix Required:** Update checkpoint logic to mark complete even with failures

---

### 🐛 Issue #3: Stage Name Inconsistency

**Problem:** Label stage uses `"labels"` (plural) in checkpoint but code expects `"label"` (singular)

**Evidence:**
- Checkpoint file: `labels.json`
- Code lookups: `CheckpointManager(stage="label")` fails

**Fix Required:** Standardize on singular or plural (recommend plural to match checkpoint files)

---

## Priority 1: Infrastructure Review via Agents (90-120 mins)

### Goal:
Use specialized agents to analyze and report on checkpoint, logging, and status issues in Stages 2 & 3.

### Agent Tasks:

#### Agent 1: Checkpoint System Analysis (30 min)
**Task:** Analyze checkpoint implementation in Stage 2 (Correction) and Stage 3 (Label)

**Scope:**
- Review `infra/checkpoint.py` implementation
- Review Stage 2 checkpoint usage in `pipeline/2_correction/__init__.py`
- Review Stage 3 checkpoint usage in `pipeline/3_label/__init__.py`
- Sample checkpoint files from accidental-president, hap-arnold, china-macro

**Questions to Answer:**
1. How does `get_remaining_pages()` determine which pages to skip?
2. When is `mark_stage_complete()` called?
3. Why isn't status updated to "completed" when all pages are done?
4. Does checkpoint properly track partial failures?
5. Is `--resume` behavior correct or should it be default?
6. What happens if stage is run without `--resume` when checkpoint exists?

**Deliverable:** Report with:
- Current behavior documented
- Issues found with severity (critical/high/medium/low)
- Recommended fixes with code snippets

---

#### Agent 2: Logging System Analysis (30 min)
**Task:** Analyze logging implementation and output quality

**Scope:**
- Review `infra/logger.py` implementation
- Examine log files from recent runs:
  - `~/Documents/book_scans/accidental-president/logs/correction_*.jsonl`
  - `~/Documents/book_scans/hap-arnold/logs/correction_*.jsonl`
  - `~/Documents/book_scans/china-macro/logs/correction_*.jsonl`
- Review how stages log errors, progress, and completion

**Questions to Answer:**
1. Are all errors properly logged?
2. Is progress tracking accurate?
3. Are log files parseable and useful for debugging?
4. What information is missing from logs?
5. Are costs properly tracked in logs?
6. Are timestamps consistent?

**Deliverable:** Report with:
- Logging patterns documented
- Issues found (missing data, inconsistencies)
- Sample log entries showing problems
- Recommended improvements

---

#### Agent 3: Status Reporting Analysis (30 min)
**Task:** Analyze status reporting across CLI commands

**Scope:**
- Review `ar.py` status commands: `library list`, `library show`, `status`
- Review how stages report completion (print statements, metadata updates)
- Test status commands on accidental-president, hap-arnold
- Compare checkpoint status vs metadata status vs library status

**Questions to Answer:**
1. Is status consistent across all reporting mechanisms?
2. Are costs properly aggregated and displayed?
3. Is completion detection reliable?
4. What information is missing from status reports?
5. Are error counts accurate?
6. How do we distinguish "failed but retryable" vs "hard failures"?

**Deliverable:** Report with:
- Status reporting flow documented
- Inconsistencies found between different views
- Missing information identified
- Recommended improvements

---

#### Agent 4: Error Handling Analysis (30 min)
**Task:** Analyze error handling and retry logic

**Scope:**
- Review retry logic in `infra/llm_client.py`
- Review error handling in Stage 2 correction
- Review error handling in Stage 3 label
- Examine specific error patterns from recent runs:
  - 422 deserialization errors (25+ instances)
  - "Response ended prematurely" errors (5+ instances)
  - OpenRouter 500 errors

**Questions to Answer:**
1. Are retries properly implemented with exponential backoff?
2. Are transient errors (network) retried differently than persistent errors (422)?
3. Is the "auto-retry failed pages" logic in correction stage working correctly?
4. Should we implement circuit breakers for repeated failures?
5. Are error messages helpful for debugging?
6. Should we track error types in checkpoint metadata?

**Deliverable:** Report with:
- Error handling patterns documented
- Retry effectiveness analyzed
- Error type classification
- Recommended improvements

---

### How to Execute Agent Analysis

**Option A: Sequential (safer, easier to review)**
```bash
# Launch one agent at a time, review report, then launch next
# Total time: ~120 minutes
```

**Option B: Parallel (faster)**
```bash
# Launch all 4 agents in one message
# Total time: ~30-40 minutes (agents run concurrently)
```

**Recommended:** Option B (parallel) since analyses are independent

---

## Priority 2: Complete Correction Stage (20-30 mins)

### Remaining Books (904 pages, ~$2.35)

Run correction with `--resume` flag on 8 incomplete books:

```bash
cd ~/go/src/github.com/jackzampolin/scanshelf

# Can run sequentially or in parallel (user's terminal)
uv run python ar.py process correct right-wing-critics --workers 30 --resume  # 50 pages
uv run python ar.py process correct immense-conspiracy --workers 30 --resume  # 132 pages
uv run python ar.py process correct ike-mccarthy --workers 30 --resume       # 64 pages
uv run python ar.py process correct groves-bomb --workers 30 --resume        # 130 pages
uv run python ar.py process correct fiery-peace --workers 30 --resume        # 187 pages
uv run python ar.py process correct china-macro --workers 30 --resume        # 52 pages
uv run python ar.py process correct china-lobby --workers 30 --resume        # 93 pages
uv run python ar.py process correct admirals --workers 30 --resume           # 196 pages
```

**Expected:** Each should complete quickly since only processing remaining pages

---

## Priority 3: Apply Fixes from Agent Reports (30-60 mins)

After agent analysis completes:

1. **Review all 4 agent reports**
2. **Prioritize fixes** (critical → high → medium → low)
3. **Implement critical fixes:**
   - Fix checkpoint status update logic
   - Fix stage name inconsistency (label vs labels)
   - Improve resume behavior / add warnings
4. **Test fixes** on a small book (e.g., hap-arnold)
5. **Document patterns** in `docs/standards/` if needed

---

## Priority 4: Run Label Stage on All Books (optional, if time)

Once correction is 100% complete, run Stage 3 (Label) on all 10 books:

```bash
# Similar cost/time to correction (~$10-12, 20-30 mins)
uv run python ar.py process label right-wing-critics --workers 30
uv run python ar.py process label immense-conspiracy --workers 30
# ... etc
```

**Note:** Wait until after fixes are applied from agent analysis!

---

## Session Goals Summary

### Must Complete:
1. ✅ Launch 4 infrastructure analysis agents (parallel)
2. ✅ Review agent reports and prioritize fixes
3. ✅ Complete correction stage on 8 remaining books (904 pages)

### Should Complete:
4. ✅ Implement critical fixes from agent reports
5. ✅ Test fixes on sample book

### Nice to Have:
6. 📋 Run label stage on all books (if time permits)
7. 📋 Document findings in `docs/standards/`

---

## Cost Tracking

### Session So Far:
- **accidental-president:** $2.79 (Stages 2+3 complete)
- **hap-arnold:** $0.71 (Stage 2, 93.8% complete)
- **Other 8 books:** ~$7.50 (Stage 2, 64-86% complete)
- **Total spent:** ~$11

### Remaining:
- **Complete Stage 2:** ~$2.35 (904 pages)
- **Run Stage 3 on 9 books:** ~$11 (3,844 pages)
- **Run Stage 4 (merge) on 9 books:** $0 (deterministic)
- **Total for all books through Stage 4:** ~$24-25

---

## Key Files Modified This Session

- `pipeline/4_merge/__init__.py` - Three-way merge implementation
- `pipeline/5_structure/__init__.py` - Updated imports, stage number
- `ar.py` - Library list status display
- All stage directories renumbered: 3→4, 4→5

---

## Remember

1. **Always use `--resume` when re-running stages** - checkpoint exists!
2. **Agent analysis will reveal systemic issues** - don't skip this step
3. **Fix infrastructure before scaling** - better to fix now than debug 10 books later
4. **Test book = hap-arnold** - small, already has checkpoint data, good for testing fixes

---

## Questions for Next Session

1. Should `--resume` be the default behavior?
2. How do we handle persistent xAI 422 errors (25+ occurrences)?
3. Should we track error types in checkpoint metadata?
4. Should we add a "retry all failed pages" command?
5. How do we distinguish "complete with failures" vs "incomplete"?

---

*End of session notes. Start next session by launching 4 infrastructure analysis agents in parallel.*
