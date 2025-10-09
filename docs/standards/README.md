# Pipeline Stage Standards

**Version**: 1.0
**Date**: 2025-10-08
**Purpose**: Production-ready patterns for Scanshelf pipeline refactor (#56)

---

## Overview

This directory contains focused documentation on the **battle-tested patterns** from our existing pipeline (OCR, Correct, Fix, Structure). These patterns **must be preserved** during refactoring.

These standards were extracted from **pre-refactor** production code:
- Old `pipeline/ocr.py`, `correct.py`, `fix.py` (now refactored → `1_ocr/`, `2_correction/`)
- Old `pipeline/structure/` (removed - future design TBD)
- Supporting utilities: `checkpoint.py`, `llm_client.py`, `logger.py`, `pricing.py`, `utils/parallel.py`

**Note**: While specific file references are now obsolete, the **patterns** remain valid.
The refactored stages (0_ingest, 1_ocr, 2_correction) implement these same patterns.

---

## Documents (Review Order)

We recommend reviewing these in order, as they build on each other:

### Core Patterns
1. **[01_stage_interface.md](01_stage_interface.md)** - How stages are initialized and structured
2. **[02_checkpointing.md](02_checkpointing.md)** - Resume capability and progress tracking
3. **[03_llm_client.md](03_llm_client.md)** - LLM API calls, retry logic, and structured outputs with schemas

### Supporting Patterns
4. **[04_cost_tracking.md](04_cost_tracking.md)** - Accurate cost tracking across runs
5. **[05_logging.md](05_logging.md)** - Structured logs + human-readable output
6. **[06_parallelization.md](06_parallelization.md)** - Thread-safe parallel processing

### Configuration & Quality
7. **[07_configuration.md](07_configuration.md)** - Per-stage model and worker configuration
8. **[08_error_handling.md](08_error_handling.md)** - Graceful degradation and debug files

### Quality Assurance
9. **[09_production_checklist.md](09_production_checklist.md)** - Is your stage production-ready?
10. **[10_anti_patterns.md](10_anti_patterns.md)** - Common mistakes to avoid

---

## How to Use

**For refactor work (issues #48-54):**

1. **Before starting**: Read docs #1-3 (core patterns)
2. **During implementation**: Reference relevant docs as needed
3. **Before PR**: Review production checklist (#9) and anti-patterns (#10)
4. **When testing**: Verify checkpoint resume, cost tracking, error handling

**For reviews:**
- Use these docs to verify refactored stages follow established patterns
- Call out deviations (with justification) in PRs

---

## Design Philosophy

Our pipeline follows **defensive programming** principles:

- **Assume failures will happen** - Incremental checkpoints, atomic saves
- **Validate at boundaries** - Input/output validation prevents cascading errors
- **Make failures observable** - Debug files + structured logs
- **Make costs transparent** - Track and report costs everywhere
- **Support incremental work** - Resume from any point, accumulate results

This is essential for processing 400+ page books that take 15+ minutes and cost $5-15 per book.

---

## Contributing

When adding new patterns:
1. Extract from working production code (not theoretical)
2. Include file:line references to examples
3. Document both correct usage AND anti-patterns
4. Update production checklist if adding requirements

---

## Questions?

Discuss in issue #56 or reach out to @jackzampolin.
