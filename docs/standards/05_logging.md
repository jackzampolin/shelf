# Logging Patterns

**Purpose**: Define structured logging patterns for pipeline stages.

---

## Overview

Pipeline logging provides **dual output**:
- **JSON logs** - Machine-parseable (JSONL format)
- **Console output** - Human-readable with icons and progress bars

**Location:** `~/Documents/book_scans/<scan_id>/logs/{stage}_{timestamp}.jsonl`

**Core principle:** Logs are structured data with consistent fields, not just strings.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Logging Flow                             │
└─────────────────────────────────────────────────────────────┘

1. INITIALIZATION
   └── create_logger(scan_id, stage)
       └── Creates dual handlers (JSON file + console)
       └── Thread-safe context management

2. LOG GENERATION
   └── Stage code calls logger methods
       └── logger.info(), logger.progress(), logger.error()
       └── Structured fields: page, cost_usd, progress, etc.

3. OUTPUT
   a) JSON Handler
      └── Writes JSONL to log file (machine-parseable)

   b) Console Handler
      └── Formats with icons and progress bars (human-readable)
```

---

## Key Patterns

### Initialization

**Pattern:** Always use `create_logger()` convenience function
```python
from logger import create_logger
logger = create_logger(scan_id, stage_name)
```

**See:** `logger.py:323-339`, `pipeline/correct.py:80`

### Log Levels

Use appropriate level:
- `debug()` - Detailed diagnostics (not shown by default)
- `info()` - Normal operations, progress, completion
- `warning()` - Unexpected but handled conditions
- `error()` - Failed operations (page errors, API failures)
- `critical()` - Stage-level failures

### Specialized Methods

**Progress tracking:**
- `logger.progress(message, current, total, **kwargs)`
- Shows progress bar in console, structured data in JSON

**Stage lifecycle:**
- `logger.start_stage(**kwargs)` - Log configuration at start
- `logger.complete_stage(duration_seconds, **kwargs)` - Log completion stats

**Page events:**
- `logger.page_event(message, page, **kwargs)` - Page-level success
- `logger.page_error(message, page, error, **kwargs)` - Page-level errors

**See:** `logger.py:225-272`, `pipeline/correct.py:826-900`

### Context Management

**Temporary context:**
```python
with logger.context_scope(worker_id=1):
    logger.info("Processing...")  # Includes worker_id
```

**Permanent context:**
```python
logger.set_context(phase="extraction")  # All future logs include phase
```

**Thread-safe:** Context modifications protected by lock for parallel workers

**See:** `logger.py:274-298`

---

## Design Principles

**Dual Output by Default**
- JSON for monitoring tools, cost analysis, debugging
- Console for interactive user feedback
- Independent formats optimized for each audience

**Thread-Safe**
- Context modifications use locks
- Safe to call from parallel workers
- Each PipelineLogger gets unique `logging.Logger` instance

**Always Cleanup**
- Use context manager: `with create_logger(...) as logger:`
- Or explicit: `try/finally: logger.close()`
- Flushes buffered logs, prevents file handle leaks

**Consistent JSON Structure**
- Every log: `timestamp`, `level`, `message`, `scan_id`, `stage`
- Optional fields: `page`, `progress`, `cost_usd`, `tokens`, `error`
- JSONL format (one JSON object per line)
- Consistent field types (timestamps=ISO8601, costs=float, pages=int)

---

## Anti-Patterns

❌ **Don't forget cleanup** - Always use context manager or explicit close
❌ **Don't mix print() and logger** - Use logger exclusively for consistency
❌ **Don't add one-off data to context** - Use kwargs instead

---

## Integration Points

- **Checkpointing:** Separate from logs (checkpoint = state, logs = events)
- **Monitoring:** External tools read JSON logs for real-time status
- **Cost Tracking:** Logs record costs but don't calculate them

---

## Summary

Production-ready logging:
1. ✅ Uses `create_logger()` for initialization
2. ✅ Outputs dual format (JSON + console)
3. ✅ Uses appropriate log levels and specialized methods
4. ✅ Manages context thread-safely
5. ✅ Always cleans up (context manager or explicit close)
6. ✅ Produces valid JSONL with consistent structure

**See:** `logger.py` for complete implementation
