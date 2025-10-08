# Error Handling Patterns

**Purpose**: Define robust error handling for resilient pipeline processing.

---

## Overview

Error handling is **multi-layered** with automatic recovery:
- **Stage-level** - Checkpoint failed, preserves partial progress
- **Page-level** - Returns error status, continues processing
- **LLM-level** - Automatic retry with exponential backoff
- **Debug output** - Saves diagnostic files

**Core principle:** Fail gracefully, preserve work, enable debugging.

---

## System Architecture

```
┌───────────────────────────────────────────────┐
│           Error Handling Layers               │
└───────────────────────────────────────────────┘

1. STAGE-LEVEL → Checkpoint failed, preserve pages
2. PAGE-LEVEL → Return status dict, continue batch
3. LLM-LEVEL → Retry 5xx/timeouts, fail fast on 4xx
4. DEBUG OUTPUT → Save diagnostic files on failures
```

---

## Key Patterns

### Stage-Level Error Handling

```python
def process_pages(self, start_page, end_page, resume=False):
    try:
        page_numbers = self._get_pages(start_page, end_page, resume)
        self._process_parallel(page_numbers)

        if self.checkpoint:
            self.checkpoint.mark_stage_complete(metadata={...})

        return self._build_result()

    except Exception as e:
        if self.checkpoint:
            self.checkpoint.mark_stage_failed(error=str(e))
        self.logger.error(f"Stage failed: {e}")
        raise
```

**See:** `checkpoint.py:387-398`

### Page-Level Error Handling

**Workers never raise exceptions:**
```python
def process_single_page(self, page_num, total_pages):
    try:
        result = self._do_processing(page_num)
        self._save_page_output(page_num, result)

        if self.checkpoint:
            self.checkpoint.mark_completed(page_num)

        return {'page': page_num, 'status': 'success', 'cost': result.get('cost', 0.0)}

    except Exception as e:
        self.logger.error("Page failed", page=page_num, error=str(e))

        with self.stats_lock:
            self.stats['failed_pages'] += 1

        return {'page': page_num, 'status': 'error', 'error': str(e)}
```

**See:** `pipeline/correct.py:683-760`, `pipeline/ocr.py:407-436`

### LLM Retry Logic

**Exponential backoff (1s, 2s, 4s):**
```python
for attempt in range(max_retries):
    try:
        response = requests.post(url, json=payload, timeout=timeout)
        response.raise_for_status()
        return response.json()

    except requests.exceptions.HTTPError as e:
        if e.response.status_code >= 500:
            # Retry 5xx server errors
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
        else:
            # Don't retry 4xx client errors
            raise

    except requests.exceptions.Timeout:
        if attempt < max_retries - 1:
            time.sleep(2 ** attempt)
            continue
        raise
```

**JSON parsing retry** (retries entire LLM call):
```python
result, usage, cost = llm_client.call_with_json_retry(
    model=self.model,
    messages=messages,
    json_parser=parse_function,
    max_retries=2
)
```

**See:** `llm_client.py:112-143`, `llm_client.py:322-385`

### Debug File Generation

```python
self.debug_dir = self.logs_dir / "debug"
self.debug_dir.mkdir(exist_ok=True)

# On JSON parse error
try:
    json.loads(response)
except json.JSONDecodeError as e:
    debug_file = self.debug_dir / f"page_{page_num:04d}_json_error.txt"
    with open(debug_file, 'w') as f:
        f.write(f"Error: {str(e)}\n\n")
        f.write("=== ORIGINAL ===\n" + original)
        f.write("\n=== EXTRACTED ===\n" + extracted)
        f.write("\n=== FIXED ===\n" + fixed)
    raise
```

**See:** `pipeline/correct.py:164-175`

---

## Design Principles

**Multi-Layered Defense**
- Stage catches catastrophic failures
- Page isolates individual failures
- LLM handles transient API issues

**Fail Gracefully**
- Workers return status (never raise)
- Partial progress preserved
- Costs tracked even on failures

**Retry Smart**
- Exponential backoff (1s, 2s, 4s)
- Retry 5xx + timeouts
- Don't retry 4xx (permanent errors)
- Accumulate costs across retries

**Debug-Friendly**
- Save inputs/outputs on failure
- Include error context
- Structured logs for analysis

---

## Error Thresholds (Future)

**Add configurable failure limits:**
```python
MAX_FAILURE_RATE = 0.10  # Abort if >10% pages fail

if failed_count / total_count > MAX_FAILURE_RATE:
    raise ValueError(f"Failure rate exceeds {MAX_FAILURE_RATE}")
```

**Suggested thresholds:**
- OCR: 5% (critical foundation)
- Correction: 10%
- Fix: 20% (targets problem subset)
- Structure: 15%

---

## Checkpoint Integration

**Preserve partial progress:**
```python
def mark_stage_failed(self, error: str):
    """Mark failed but preserve completed pages."""
    self._state['status'] = 'failed'
    self._state['error'] = error
    self._state['failed_at'] = datetime.now().isoformat()
    self._save_checkpoint()  # Keeps completed_pages
```

**Benefits:** Resume skips completed pages, costs preserved.

**See:** `checkpoint.py:387-398`

---

## Anti-Patterns

❌ Raising from workers
❌ Retrying 4xx errors
❌ Swallowing errors without logging
❌ Marking complete before save
❌ Resetting checkpoint on error

---

## Summary

Production-ready error handling:
1. ✅ Stage try/except with mark_stage_failed()
2. ✅ Worker returns status dict
3. ✅ LLM automatic retry (exponential backoff)
4. ✅ Debug files on failures
5. ✅ Partial progress preserved
6. ✅ Thread-safe error tracking
7. ✅ Error thresholds (future)

**See:** `llm_client.py`, `checkpoint.py`, `pipeline/correct.py`
