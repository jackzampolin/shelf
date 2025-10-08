# Production Readiness Checklist

**Purpose**: Quick reference for verifying stages are production-ready.

---

## Core Functionality

- [ ] **Stage Interface** - Standard initialization and process methods ([01_stage_interface.md](01_stage_interface.md))
  - Accepts: `scan_id`, `storage_root`, `enable_checkpoints`, `logger`, `model`, `max_workers`
  - Returns: Dict with `total_cost`, `statistics`, `pages_processed`

- [ ] **Input/Output Validation** - Files exist, JSON valid, required fields present
  - Validate before processing
  - Fail fast with clear errors

---

## Checkpointing

- [ ] **Resume Support** - Can continue from checkpoint ([02_checkpointing.md](02_checkpointing.md))
  - `checkpoint.get_remaining_pages()` filters completed work
  - Logs resume info (pages skipped, cost saved)

- [ ] **Progress Tracking** - Mark pages complete incrementally
  - Save **before** marking checkpoint
  - Mark stage complete with metadata
  - Mark stage failed on exceptions

---

## Cost Tracking

- [ ] **Accumulate Costs** - Load existing from checkpoint ([04_cost_tracking.md](04_cost_tracking.md))
  - Don't reset to 0 on resume
  - Track per LLM call (thread-safe)
  - Save to checkpoint metadata

---

## Logging

- [ ] **Structured Logging** - JSON + console output ([05_logging.md](05_logging.md))
  - Log stage start/complete with config
  - Progress updates every N pages
  - Errors with page context

---

## Parallelization

- [ ] **Thread-Safe Execution** - Uses locks for shared state ([06_parallelization.md](06_parallelization.md))
  - Stats lock for counters
  - Rate limiting for LLM calls (if applicable)
  - Checkpoint is thread-safe by default

---

## Configuration

- [ ] **Configurable Models** - Uses Config with override ([07_configuration.md](07_configuration.md))
  - `Config.get_model_for_stage("stage_name")`
  - Constructor parameter allows override
  - Worker counts from config

---

## Error Handling

- [ ] **Graceful Degradation** - Never raise from workers ([08_error_handling.md](08_error_handling.md))
  - Workers return status dict
  - Stage try/except with `mark_stage_failed()`
  - LLM retry with exponential backoff
  - Debug files on failures

---

## Testing

- [ ] **Unit Tests** - Core processing logic
- [ ] **Integration Tests** - Real inputs end-to-end
- [ ] **Checkpoint Resume** - Verify partial completion works
- [ ] **Error Paths** - Test failure handling

---

## Quick Verification

**Run this mental checklist before PR:**

1. Can I resume from checkpoint after crash? ✓
2. Are costs accumulated across runs? ✓
3. Do workers return status (not raise)? ✓
4. Are stats updates thread-safe? ✓
5. Does logger output JSON + console? ✓
6. Are errors logged with context? ✓
7. Is model configurable via Config? ✓

---

## Anti-Patterns to Avoid

See [10_anti_patterns.md](10_anti_patterns.md) for detailed examples.

**Most common mistakes:**
- ❌ Resetting costs on resume
- ❌ Marking complete before save
- ❌ Raising from workers
- ❌ Hardcoding model names
- ❌ No resume logging
