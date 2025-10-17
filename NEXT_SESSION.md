# Next Session: Complete Stage 3 (Label) Refactoring

## Current Progress

### ✅ Completed
1. **Analyzed Stage 2 patterns** - Documented gold standard (460 lines, clean LLM batch processing)
2. **Analyzed Stage 4 (Merge)** - Refactored in 4 commits (saved 30 lines, applied all patterns)
3. **Generated refactoring plan for Stage 3 (Label)** - 7-commit plan to match Stage 2
4. **Started Commit 1** - Created `pipeline/3_label/prompts.py` and added imports

### 🚧 In Progress: Commit 1 - Extract prompts to prompts.py

**What's Done:**
- ✅ Created `pipeline/3_label/prompts.py` (~245 lines)
- ✅ Added imports to `__init__.py` (lines 38-42)

**What's Left:**
- Replace `self._build_system_prompt()` with `SYSTEM_PROMPT` constant (line 419)
- Replace `self._build_user_prompt(...)` with `build_user_prompt(...)` (lines 420-426)
- Replace `self._format_ocr_for_prompt(ocr_page)` with `json.dumps(ocr_page.model_dump(), indent=2)` (line 416)
- Remove methods: `_build_system_prompt()`, `_build_user_prompt()`, `_get_default_region()`, `_format_ocr_for_prompt()` (lines 520-732)
- Update prompts.py to use `json.dumps()` instead of custom formatting

**Simplification:**
Instead of `format_ocr_for_prompt()`, use Stage 2's pattern:
```python
# In __init__.py line 416
ocr_text = json.dumps(ocr_page.model_dump(), indent=2)

# Remove format_ocr_for_prompt from prompts.py and imports
```

---

## Remaining Commits (6 commits)

### Commit 1 Completion Steps

1. **Update _label_page_with_vision method** (line 415-426):
```python
# Build OCR text representation for the prompt
ocr_text = json.dumps(ocr_page.model_dump(), indent=2)

# Build the vision prompt with page context
user_prompt = build_user_prompt(
    ocr_page=ocr_page,
    ocr_text=ocr_text,
    current_page=ocr_page.page_number,
    total_pages=total_pages,
    book_metadata=book_metadata
)

# System prompt is now a constant
# Remove self._build_system_prompt() call, use SYSTEM_PROMPT directly
```

2. **Update LLM call** (lines 487-490):
```python
messages=[
    {"role": "system", "content": SYSTEM_PROMPT},  # Use constant
    {"role": "user", "content": user_prompt},
    {"role": "assistant", "content": '{"printed_page_number":'}
],
```

3. **Remove old prompt methods** (lines 520-732):
- Delete `_build_system_prompt()` (~147 lines)
- Delete `_build_user_prompt()` (~42 lines)
- Delete `_get_default_region()` (~8 lines)
- Delete `_format_ocr_for_prompt()` (~9 lines)

4. **Update prompts.py** - Remove `format_ocr_for_prompt()`:
```python
# Remove the format_ocr_for_prompt function entirely
# Update docstring in build_user_prompt to note that ocr_text is pre-formatted JSON
```

5. **Update imports in __init__.py** (line 42):
```python
# Remove format_ocr_for_prompt from imports
build_user_prompt = label_prompts.build_user_prompt
```

**Expected Result:** 821 lines → ~615 lines (-206 lines)

**Test:**
```bash
uv run python -c "from pipeline.3_label import VisionLabeler; print('OK')"
```

**Commit Message:**
```
refactor: extract prompts from label stage to prompts.py

Moves all prompt construction to pipeline/3_label/prompts.py:
- SYSTEM_PROMPT constant (~150 lines)
- build_user_prompt() function (~50 lines)

Simplifications vs original:
- Use json.dumps() for OCR formatting (Stage 2 pattern)
- Removed format_ocr_for_prompt() helper (unnecessary)
- Prompts are now first-class artifacts (like Stage 2)

Benefits:
- Reduces __init__.py by ~206 lines
- Prompts can be versioned/tested independently
- Easier prompt iteration without touching business logic
- Consistent with Stage 2 (Correction) pattern

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
```

---

### Commit 2: Replace LLMClient with LLMBatchClient

**Goal:** Change imports and initialization to use batch client

**Changes:**
1. Line 24: `from infra.llm_client import LLMClient` → `from infra.llm_batch_client import LLMBatchClient`
2. Line 24: Add `from infra.llm_models import LLMRequest, LLMResult, EventData, LLMEvent, RequestPhase`
3. Line 76: `self.llm_client = None` → `self.batch_client = None`
4. Lines 109-110: Change initialization (copy from Stage 2 lines 98-107):
```python
# Remove self.llm_client = LLMClient()
# Will add batch_client initialization in Commit 3
```

**Expected:** ~615 lines → ~610 lines (mostly import changes)

**Test:** `uv run python -c "from pipeline.3_label import VisionLabeler; print('OK')"`

---

### Commit 3: Add parallel batch loading pattern

**Goal:** Pre-load all pages in parallel and build LLMRequest objects

**Reference:** Stage 2 lines 134-247

**Changes:**

1. **Add imports** (top of file):
```python
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
```

2. **Initialize batch client with failure logging** (after checkpoint init, ~line 160):
```python
# Initialize batch LLM client with failure logging
self.batch_client = LLMBatchClient(
    max_workers=self.max_workers,
    rate_limit=150,
    max_retries=self.max_retries,
    retry_jitter=(1.0, 3.0),
    json_retry_budget=2,
    verbose=True,
    progress_interval=0.5,
    log_dir=book_dir / "labels" / "logs"  # Will change to storage API in Commit 5
)
```

3. **Replace task building with parallel loading** (lines 178-194):
```python
# Pre-load OCR data and prepare requests (parallelized)
print(f"\n   Loading {len(pages_to_process)} pages...")
load_start_time = time.time()
load_progress = ProgressBar(total=len(pages_to_process), prefix="   ", width=40, unit="pages")
load_progress.update(0, suffix="loading...")

requests = []
page_data_map = {}
completed_loads = 0
load_lock = threading.Lock()

# Build JSON schema once (shared across all requests)
response_schema = {
    "type": "json_schema",
    "json_schema": {
        "name": "page_labeling",
        "strict": True,
        "schema": LabelPageOutput.model_json_schema()
    }
}

def load_page(page_num):
    """Load and prepare a single page (called in parallel)."""
    ocr_file = ocr_dir / f"page_{page_num:04d}.json"
    page_file = source_dir / f"page_{page_num:04d}.png"

    if not ocr_file.exists() or not page_file.exists():
        return None

    try:
        # Load OCR data
        with open(ocr_file, 'r') as f:
            ocr_data = json.load(f)
        ocr_page = OCRPageOutput(**ocr_data)

        # Load and downsample image
        page_image = Image.open(page_file)
        page_image = downsample_for_vision(page_image)

        # Build page-specific prompt with book context
        ocr_text = json.dumps(ocr_page.model_dump(), indent=2)
        user_prompt = build_user_prompt(
            ocr_page=ocr_page,
            ocr_text=ocr_text,
            current_page=page_num,
            total_pages=total_pages,
            book_metadata=metadata
        )

        # Create LLM request
        request = LLMRequest(
            id=f"page_{page_num:04d}",
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
                {"role": "assistant", "content": '{"printed_page_number":'}
            ],
            temperature=0.1,
            timeout=180,
            images=[page_image],
            response_format=response_schema,
            metadata={
                'page_num': page_num,
                'ocr_page_number': ocr_page.page_number
            }
        )

        return (page_num, ocr_page, request)

    except Exception as e:
        print(f"❌ Failed to load page {page_num}: {e}", file=sys.stderr)
        return None

# Parallel loading
import os
load_workers = os.cpu_count() or 4

with ThreadPoolExecutor(max_workers=load_workers) as executor:
    future_to_page = {
        executor.submit(load_page, page_num): page_num
        for page_num in pages_to_process
    }

    for future in as_completed(future_to_page):
        result = future.result()
        if result:
            page_num, ocr_page, request = result
            requests.append(request)
            page_data_map[page_num] = {'ocr_page': ocr_page, 'request': request}

        with load_lock:
            completed_loads += 1
            load_progress.update(completed_loads, suffix=f"{len(requests)} loaded")

load_elapsed = time.time() - load_start_time
load_progress.finish(f"   ✓ {len(requests)} pages loaded in {load_elapsed:.1f}s")

if len(requests) == 0:
    print("✅ No valid pages to process")
    return
```

**Expected:** ~610 → ~750 lines (+140 lines for loading pattern)

**Test:** Run on small batch to verify loading works

---

### Commit 4: Replace manual retry with batch processing

**Goal:** Remove manual retry loop, add callback methods, use batch_client.process_batch()

**Reference:** Stage 2 lines 254-460

**Remove:** Lines 211-272 (manual retry while loop, ~62 lines)

**Add:** Batch processing with callbacks:

```python
# Setup progress tracking
print(f"\n   Labeling {len(requests)} pages...")
label_start_time = time.time()
progress = ProgressBar(total=len(requests), prefix="   ", width=40, unit="pages")
progress.update(0, suffix="starting...")
failed_pages = []

# Callback wrappers (bind local state to class methods)
def on_event(event: EventData):
    self._handle_progress_event(event, progress, len(requests))

def on_result(result: LLMResult):
    self._handle_result(result, failed_pages, book_dir / "labels")

# Process batch with callbacks
results = self.batch_client.process_batch(
    requests,
    json_parser=json.loads,
    on_event=on_event,
    on_result=on_result
)

# Finish progress bar
label_elapsed = time.time() - label_start_time
batch_stats = self.batch_client.get_batch_stats(total_requests=len(requests))
progress.finish(f"   ✓ {batch_stats.completed}/{len(requests)} pages labeled in {label_elapsed:.1f}s")

errors = len(failed_pages)
if errors > 0:
    print(f"   ⚠️  {errors} pages failed: {sorted(failed_pages)[:10]}" +
          (f" and {len(failed_pages)-10} more" if len(failed_pages) > 10 else ""))
```

**Add callback methods** (copy from Stage 2, adapt for label):

```python
def _handle_progress_event(self, event: EventData, progress: ProgressBar, total_requests: int):
    """Handle progress event for batch processing."""
    try:
        if event.event_type == LLMEvent.PROGRESS:
            active = self.batch_client.get_active_requests()
            recent = self.batch_client.get_recent_completions()

            batch_stats = self.batch_client.get_batch_stats(total_requests=total_requests)
            rate_util = event.rate_limit_status.get('utilization', 0) if event.rate_limit_status else 0
            suffix = f"${batch_stats.total_cost_usd:.2f} | {rate_util:.0%} rate"

            # Show executing requests
            for req_id, status in active.items():
                if status.phase == RequestPhase.EXECUTING:
                    page_id = req_id.replace('page_', 'p')
                    elapsed = status.phase_elapsed
                    if status.retry_count > 0:
                        progress.add_sub_line(req_id,
                            f"{page_id}: Executing... ({elapsed:.1f}s, retry {status.retry_count}/{self.max_retries})")
                    else:
                        progress.add_sub_line(req_id, f"{page_id}: Executing... ({elapsed:.1f}s)")

            # Show recent completions
            for req_id, comp in recent.items():
                page_id = req_id.replace('page_', 'p')
                if comp.success:
                    progress.add_sub_line(req_id,
                        f"{page_id}: ✓ ({comp.total_time_seconds:.1f}s, ${comp.cost_usd:.4f})")
                else:
                    error_preview = comp.error_message[:30] if comp.error_message else 'unknown'
                    progress.add_sub_line(req_id,
                        f"{page_id}: ✗ ({comp.total_time_seconds:.1f}s) - {error_preview}")

            progress.update(event.completed, suffix=suffix)

        elif event.event_type == LLMEvent.RATE_LIMITED:
            progress.set_status(f"⏸️  Rate limited, resuming in {event.eta_seconds:.0f}s")

    except Exception as e:
        import sys, traceback
        error_msg = f"ERROR: Progress update failed: {type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
        print(error_msg, file=sys.stderr, flush=True)
        # Don't raise - let processing continue

def _handle_result(self, result: LLMResult, failed_pages: list, labels_dir: Path) -> int:
    """Handle LLM result - save successful pages, track failures."""
    try:
        page_num = result.request.metadata['page_num']

        if result.success:
            try:
                # Add metadata to label data
                label_data = result.parsed_json
                if label_data is None:
                    raise ValueError("parsed_json is None for successful result")

                label_data['page_number'] = result.request.metadata['ocr_page_number']
                label_data['model_used'] = self.model
                label_data['processing_cost'] = result.cost_usd
                label_data['timestamp'] = datetime.now().isoformat()

                # Calculate summary stats
                avg_class_conf = sum(b.get('classification_confidence', 0) for b in label_data['blocks']) / len(label_data['blocks']) if label_data['blocks'] else 0
                avg_conf = sum(
                    p.get('confidence', 1.0)
                    for b in label_data['blocks']
                    for p in b.get('paragraphs', [])
                ) / sum(len(b.get('paragraphs', [])) for b in label_data['blocks']) if label_data['blocks'] else 1.0

                label_data['total_blocks'] = len(label_data['blocks'])
                label_data['avg_classification_confidence'] = round(avg_class_conf, 3)
                label_data['avg_confidence'] = round(avg_conf, 3)

                # Validate output against schema
                validated = LabelPageOutput(**label_data)
                label_data = validated.model_dump()

                # Save label output (manual for now, will use storage.label.save_page in Commit 5)
                output_file = labels_dir / f"page_{page_num:04d}.json"
                temp_file = output_file.with_suffix('.json.tmp')

                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(label_data, f, indent=2)

                temp_file.replace(output_file)

                # Mark checkpoint complete
                if self.checkpoint:
                    self.checkpoint.mark_completed(page_num, cost_usd=result.cost_usd)

                return 1  # Success

            except Exception as e:
                import sys, traceback
                failed_pages.append(page_num)
                print(f"❌ Failed to save page {page_num} result: {traceback.format_exc()}",
                      file=sys.stderr, flush=True)
                return 0
        else:
            # Permanent failure (already logged by LLMBatchClient)
            failed_pages.append(page_num)
            return 0

    except Exception as e:
        # Critical: Catch errors from metadata access
        import sys, traceback
        error_msg = f"CRITICAL: on_result callback failed: {type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
        print(error_msg, file=sys.stderr, flush=True)

        try:
            if hasattr(result, 'request') and result.request and hasattr(result.request, 'metadata'):
                page_num = result.request.metadata.get('page_num', 'unknown')
                if page_num != 'unknown':
                    failed_pages.append(page_num)
        except:
            pass

        return 0
```

**Remove methods:**
- `_process_single_page()` (absorbed into callbacks)
- `_label_page_with_vision()` (absorbed into load_page)
- `_image_to_base64()` (not needed)

**Update final stats** (lines 281-324):
```python
# Get final stats from batch client (single source of truth)
final_stats = self.batch_client.get_batch_stats(total_requests=total_pages)
completed = final_stats.completed
total_cost = final_stats.total_cost_usd
```

**Expected:** ~750 → ~680 lines (-70 lines of manual retry, +135 lines of callbacks = net +65)

**Test:** Run on small book to verify batch processing works

---

### Commit 5: Migrate to BookStorage APIs

**Goal:** Replace all manual path construction with storage.label.* calls

**Changes:**

1. **Add BookStorage import** (line 26):
```python
from infra.book_storage import BookStorage
```

2. **Initialize storage** (lines 86-96):
```python
# Initialize storage manager
try:
    storage = BookStorage(scan_id=book_title, storage_root=self.storage_root)
    storage.label.validate_inputs()  # Validates OCR outputs exist
except FileNotFoundError as e:
    print(f"❌ {e}")
    return

# Load metadata
metadata = storage.load_metadata()
```

3. **Use storage for all paths:**
- Line 104: `logs_dir = storage.logs_dir`
- Line 107: `log_dir = storage.label.get_log_dir()`
- Line 139: `labels_dir = storage.label.output_dir`
- Line 159: `source_dir` → use `storage.source.output_dir`
- In load_page: `storage.label.input_page(page_num)`, `storage.label.source_image(page_num)`

4. **Use storage.label.save_page()** in _handle_result:
```python
# Replace manual file write with:
storage.label.save_page(
    page_num=page_num,
    data=label_data,
    cost_usd=result.cost_usd,
    processing_time=result.total_time_seconds
)
```

5. **Update metadata** (lines 296-302):
```python
storage.update_metadata({
    'labels_complete': True,
    'labels_completion_date': datetime.now().isoformat(),
    'labels_total_cost': total_cost
})
```

**Expected:** ~680 → ~640 lines (-40 lines of manual path construction)

**Test:** Full label run on test book

---

### Commit 6: Use checkpoint property and remove manual stats

**Goal:** Replace manual checkpoint/stats with storage.label.checkpoint

**Changes:**

1. **Remove from __init__** (lines 67-74):
```python
# Remove self.stats dict, self.stats_lock, self.logger, self.checkpoint
```

2. **Use checkpoint property** (lines 112-147):
```python
# Remove manual CheckpointManager instantiation
# Replace with:
if self.enable_checkpoints:
    checkpoint = storage.label.checkpoint
    if not resume:
        if not checkpoint.reset(confirm=True):
            print("   Use --resume to continue from checkpoint.")
            return
```

3. **Pass storage/checkpoint through callbacks:**
```python
def on_result(result: LLMResult):
    self._handle_result(result, failed_pages, storage)
```

4. **Update _handle_result signature:**
```python
def _handle_result(self, result: LLMResult, failed_pages: list, storage: BookStorage) -> int:
    # Use storage.label.save_page()
    # Use storage.label.checkpoint.mark_completed()
```

5. **Get final stats from checkpoint:**
```python
if errors == 0:
    storage.label.checkpoint.mark_stage_complete(metadata={
        "model": self.model,
        "total_cost_usd": total_cost,
        "pages_processed": completed
    })
```

**Expected:** ~640 → ~575 lines (-65 lines)

**Test:** Test checkpoint reset, resume, and completion

---

### Commit 7: Remove clean_stage() and final cleanup

**Goal:** Use inherited StageView.clean_stage()

**Remove:**
- Lines 734-794: `clean_stage()` method (~61 lines)
- Remove `self.logger` references and create_logger import
- Remove unused imports

**Expected:** ~575 → ~515 lines (-60 lines)

**Final cleanup:**
- Remove base64, io imports (not needed)
- Remove create_logger import
- Ensure all Stage 2 patterns applied

**Test:**
```bash
# Test clean command
uv run python ar.py process clean label accidental-president

# Full end-to-end
uv run python ar.py process label accidental-president
```

---

## Final Expected State

**Files:**
- `pipeline/3_label/__init__.py`: ~515 lines (down from 821, -306 lines / -37%)
- `pipeline/3_label/prompts.py`: ~245 lines (new file)
- Total: ~760 lines (better organized)

**Patterns Applied:**
- ✅ LLMBatchClient with parallel batch processing
- ✅ Extracted prompts (SYSTEM_PROMPT + build_user_prompt)
- ✅ BookStorage APIs (storage.label.*)
- ✅ Checkpoint property (storage.label.checkpoint)
- ✅ checkpoint.reset(confirm=True) pattern
- ✅ storage.label.save_page() for atomic writes
- ✅ Inherited clean_stage()
- ✅ Callback methods (_handle_progress_event, _handle_result)
- ✅ No manual retry logic
- ✅ No self.stats dict
- ✅ Simplified OCR formatting (json.dumps like Stage 2)

---

## Testing Strategy

**After Each Commit:**
```bash
# Syntax check
python3 -m py_compile pipeline/3_label/__init__.py

# Import test
uv run python -c "from pipeline.3_label import VisionLabeler; print('OK')"
```

**After Commit 4 (batch processing works):**
```bash
# Small batch test
uv run python ar.py process label accidental-president --start 1 --end 10
```

**After Commit 7 (final):**
```bash
# Full book test
uv run python ar.py process label accidental-president

# Resume test
uv run python ar.py process label accidental-president --resume

# Clean test
uv run python ar.py process clean label accidental-president
```

---

## Success Criteria

- [ ] All tests pass
- [ ] Label stage completes on test book
- [ ] Output JSON matches pre-refactor format
- [ ] Checkpoint resume works
- [ ] Cost tracking accurate
- [ ] Progress bar shows real-time updates
- [ ] Clean command works
- [ ] Code reduced by ~37% (821 → ~515 lines)
- [ ] All Stage 2 patterns applied

---

## Notes

- **Commit 1 is mostly done** - just need to replace method calls and remove old methods
- **Commits 2-7 are straightforward** - follow Stage 2 patterns closely
- **Stage 3 will match Stage 2 quality** after this refactor
- **Total time estimate:** ~3-4 hours (similar to Stage 2 refactor)
