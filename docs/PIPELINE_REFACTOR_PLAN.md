# Pipeline Refactor Plan

Comprehensive plan to harden the pipeline before reprocessing all books.

## Overview

Before doing a clean slate reprocessing (issue #30), we need to ensure the pipeline is:
1. **Observable** - Can track progress in real-time
2. **Reliable** - Can resume from failures
3. **Fast** - Maximally parallelized
4. **Optimal** - LLM prompts are cost-effective
5. **Consistent** - Library metadata stays in sync

## Issues Created

### High Priority (Blocking #30)

**#32: Unified Logging System**
- Structured JSON logging across all stages
- Real-time progress tracking
- Centralized log aggregation
- `ar monitor <scan-id>` command for live progress
- **Why**: Need visibility into long-running processes

**#33: Checkpoint System**
- Persistent checkpoints after each batch
- Resume from last successful point
- Validate checkpoints before resuming
- `--resume` flag for all pipeline commands
- **Why**: Avoid reprocessing on failures (saves time/money)

**#36: Library Metadata Consistency**
- Atomic library updates throughout pipeline
- Validation command to detect drift
- Auto-sync after each stage
- Pre/post-flight checks
- **Why**: Prevent getting into bad states

### Medium Priority (Nice to have)

**#34: Maximize Parallelization**
- Parallelize OCR stage (10-20x speedup)
- Test higher worker counts (50-100)
- Parallel footnote + bibliography extraction
- Configurable `--workers` flags
- **Why**: Faster processing = less wait time

**#35: LLM Prompt Optimization**
- Audit all 8 prompts across pipeline
- A/B test variations
- Optimize for cost and quality
- Document design decisions
- **Why**: 10-20% cost reduction (significant at scale)

## Dependency Graph

```
#28 (Structure Refactor) ✅ DONE
    ↓
#32 (Logging) → #33 (Checkpoints) → #36 (Library Sync)
    ↓                                       ↓
#34 (Parallelization)              #30 (Clean Slate)
    ↓                                       ↓
#35 (Prompt Optimization)          Reprocess All Books
```

## Implementation Order

### Phase 1: Foundation (Week 1)
1. **#32 Unified Logging**
   - Create `logger.py` module
   - Update all pipeline stages
   - Add `ar monitor` command
   - **Deliverable**: Real-time progress tracking

2. **#33 Checkpoint System**
   - Create `checkpoint.py` module
   - Add checkpoints to all stages
   - Add `--resume` flag
   - **Deliverable**: Resumable pipelines

### Phase 2: Reliability (Week 1-2)
3. **#36 Library Consistency**
   - Add atomic update context manager
   - Update all pipeline stages
   - Add `ar library validate` command
   - **Deliverable**: Consistent library metadata

### Phase 3: Optimization (Week 2-3)
4. **#34 Parallelization** (Optional)
   - Parallelize OCR
   - Test higher worker counts
   - Add `--workers` flags
   - **Deliverable**: 2-5x speedup

5. **#35 Prompt Optimization** (Optional)
   - Extract all prompts to docs/
   - A/B test variations
   - Update with optimal versions
   - **Deliverable**: 10-20% cost reduction

### Phase 4: Clean Slate (Week 3-4)
6. **#30 Reprocess All Books**
   - Delete old processing artifacts
   - Reset library to registered state
   - Reprocess all books with consistent pipeline
   - **Deliverable**: Clean, consistent corpus

## Success Metrics

### Observability
- [x] Can view progress in real-time
- [x] Structured logs for all stages
- [x] Cost tracking per stage

### Reliability
- [x] Can resume from any failure
- [x] Library stays in sync with disk
- [x] Validation catches inconsistencies

### Performance
- [x] OCR parallelized
- [x] Optimal worker counts documented
- [x] Prompts optimized for cost

### Quality
- [x] All books use schema v2.0
- [x] Consistent structure across corpus
- [x] Validation passes for all books

## Testing Strategy

### Per-Issue Testing
- Test each feature in isolation
- Use small test book (~100 pages)
- Verify doesn't break existing pipeline

### Integration Testing
- Test full pipeline with all features
- Use medium book (~300 pages)
- Monitor logs, checkpoints, library updates

### Production Testing
- Test on one real book first
- Monitor costs and quality
- Only proceed to batch if successful

## Cost Estimates

### Current State
- Per book: ~$12 (OCR free, correction $10, fix $1, structure $0.50)
- 7 books × $12 = **$84 total**

### After Optimizations
- Prompt optimization: 10-20% reduction → ~$10/book
- 7 books × $10 = **$70 total**
- **Savings: $14**

### Time Estimates
- Current: ~2-4 hours per book (serial processing)
- After parallelization: ~30-60 minutes per book
- **7 books: 3.5-7 hours instead of 14-28 hours**

## Risk Mitigation

### What Could Go Wrong?

1. **Checkpoints corrupt** → Validation catches this
2. **Library out of sync** → Validation command detects
3. **Logs fill disk** → Rotate logs automatically
4. **Parallelization causes rate limits** → Configurable workers
5. **Prompt changes reduce quality** → A/B test before deploying

### Rollback Strategy

- Keep old pipeline code in git history
- Test new features on one book first
- Can always revert to pre-refactor state
- Source PDFs are never modified

## Next Steps

1. **Review this plan** - Get feedback
2. **Prioritize issues** - Which are must-have vs nice-to-have?
3. **Start implementation** - Begin with #32 (logging)
4. **Test incrementally** - Validate each feature works
5. **Execute #30** - Clean slate reprocessing

## Questions

- Should we do all issues or just high priority?
- Test on real books or synthetic test data?
- What's acceptable cost for reprocessing?
- Timeline expectations?

---

**Status**: Planning phase
**Last Updated**: 2025-10-01
**Owner**: @jackzampolin
