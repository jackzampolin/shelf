# Parallelization Patterns

**Purpose**: Define thread-safe parallel processing patterns for pipeline stages.

---

## Overview

All stages use **ThreadPoolExecutor** with varying worker counts:
- OCR: 8 workers (CPU-bound)
- Correction: 30 workers (LLM, 150 calls/min limit)
- Fix: 15 workers
- Structure: 10-30 workers

**Core principle:** Consistent thread-safety through lock patterns.

---

## System Architecture

```
┌───────────────────────────────────────────────┐
│         Parallelization Components            │
└───────────────────────────────────────────────┘

1. CONFIG
   └── config/parallelization.py (worker counts)

2. EXECUTION
   └── ParallelProcessor (new) or ThreadPoolExecutor (legacy)

3. THREAD-SAFETY
   └── Stats lock, checkpoint lock, rate limiter lock
```

---

## Key Components

### Configuration
**Source:** `config/parallelization.py`
- Centralized worker counts per stage
- Optional rate limits for LLM stages

### ParallelProcessor (Recommended)
**Pattern:** `utils/parallel.py:51-214`
- Thread-safe statistics built-in
- Progress/result callbacks
- Optional rate limiting

**Usage:**
```python
processor = ParallelProcessor(
    max_workers=30,
    rate_limit=150,
    progress_callback=on_progress
)
results = processor.process(items, worker_func)
```

**See:** `pipeline/structure/extractor.py:376-439`

### ThreadPoolExecutor (Legacy)
**Pattern:** OCR, Correction, Fix stages
```python
with ThreadPoolExecutor(max_workers=n) as executor:
    futures = {executor.submit(func, item): item for item in items}
    for future in as_completed(futures):
        result = future.result()
        with self.stats_lock:
            self.stats['count'] += 1
        checkpoint.mark_completed(item)
```

**See:** `pipeline/correct.py:762-896`, `pipeline/ocr.py:174-405`

### Rate Limiting
**Class:** `RateLimiter` (`utils/parallel.py:25-49`)
- Thread-safe API throttling
- Blocks workers if calling too fast

**Usage:**
```python
rate_limiter = RateLimiter(calls_per_minute=150)
rate_limiter.wait()  # Before each API call
```

---

## Design Principles

**Thread-Safe Statistics**
- Protect shared counters with `self.stats_lock`
- Statistics are accumulators only (never decrease)

**Checkpoint Integration**
- CheckpointManager is thread-safe internally
- Workers call `checkpoint.mark_completed()` directly

**Lock Ordering**
- Never hold multiple locks
- Don't call checkpoint inside stats_lock

**Error Handling**
- Workers return status dicts, don't raise exceptions
- Log errors, continue processing

---

## Thread-Safety Requirements

**Shared Stats:**
```python
self.stats_lock = threading.Lock()
with self.stats_lock:
    self.stats['total_cost'] += cost
```

**Checkpoint (thread-safe by default):**
```python
checkpoint.mark_completed(page_num)
```

**Logger (thread-safe by default):**
```python
logger.info("Processing", page=page_num)
```

---

## Anti-Patterns

❌ Modifying stats without lock
❌ Raising exceptions from workers
❌ Holding multiple locks

---

## Summary

Production parallelization:
1. ✅ Configure workers in `config/parallelization.py`
2. ✅ Use ParallelProcessor or ThreadPoolExecutor
3. ✅ Protect stats with locks
4. ✅ Return status from workers
5. ✅ Respect lock ordering

**See:** `utils/parallel.py`, `config/parallelization.py`
