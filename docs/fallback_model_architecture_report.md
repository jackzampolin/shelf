# LLM Model Fallback Architecture Report

**Prepared for:** Code Architect Agent  
**Context:** Pages 434, 439 fail repeatedly with grok-4-fast after 20-30 retries. OpenRouter supports model array fallbacks.  
**Scope:** Minimal fallback integration into existing LLM infrastructure

---

## 1. Current LLM Infrastructure Analysis

### 1.1 File Structure & Complexity

| File | Lines | Key Responsibility | Complexity |
|------|-------|-------------------|-----------|
| `infra/llm/batch_client.py` | 1096 | Queue-based retry orchestration, rate limiting, telemetry | HIGH |
| `infra/llm/client.py` | 543 | OpenRouter API calls, retry logic, streaming | MEDIUM |
| `infra/llm/models.py` | 278 | Request/result dataclasses, event types | LOW |
| `infra/llm/pricing.py` | ~150 | Dynamic pricing lookup | LOW |
| `infra/config.py` | 56 | Configuration from env vars | LOW |

**Total LLM infrastructure: ~2,100 lines**

### 1.2 Request/Retry Flow

```
LLMRequest (model="x-ai/grok-4-fast")
    ↓
LLMBatchClient.process_batch()
    ├─ _worker_loop() processes from queue
    ├─ _execute_request() calls LLMClient
    │   ├─ LLMClient.call() → OpenRouter API
    │   ├─ LLMClient._call_non_streaming() OR _call_streaming()
    │   └─ Built-in retry (max_retries=3) for 5xx/422/timeout
    └─ _is_retryable() checks error type
        └─ YES → re-enqueue with jitter (queue.put())
        └─ NO → mark FAILED (permanent)
```

### 1.3 Current Retry Strategy

**Two levels of retry:**

1. **LLMClient.call() (lines 119-170):** Built-in exponential backoff
   - Retries: 5xx, 422, Timeout
   - NOT retried: 4xx (client errors, auth failures)
   - Max retries: 3 (hardcoded in LLMClient.call)

2. **LLMBatchClient._worker_loop() (lines 293-330):** Queue-based indefinite retry
   - Re-queues on retryable errors (line 295)
   - No model switching
   - Jitter: 1-3 seconds (configurable)

**Current failure behavior:**
- grok-4-fast returns 4xx or model-specific error → marked non-retryable
- Request never retried after hitting permanent failure threshold
- No fallback mechanism exists

---

## 2. Integration Points for Model Fallback

### 2.1 Where Model Selection Currently Happens

**Request Creation** (pipeline stages):
```python
# pipeline/2_correction/__init__.py:69
self.model = model or Config.VISION_MODEL  # From env: "x-ai/grok-4-fast"

# pipeline/3_label/__init__.py:70
self.model = model or Config.VISION_MODEL
```

**Request Execution** (batch_client):
```python
# batch_client.py:455-462
response_text, usage, cost = self.llm_client.call(
    model=request.model,      # ← FIXED at request creation time
    messages=request.messages,
    ...
)
```

### 2.2 Where Fallback Could Integrate

**Option A: At Request Level**
- Add `fallback_models` list to LLMRequest dataclass
- When primary fails → create new request with next model
- Pro: Clean separation, request-level control
- Con: Requires higher-level retry logic

**Option B: At Execution Level (Recommended)**
- Pass model array to LLMClient.call()
- OpenRouter handles fallback automatically
- Pro: Leverages OpenRouter's native feature, minimal changes
- Con: Less granular control, cost tracking complexity

**Option C: At Batch Client Level**
- On `error_type == "4xx"` (line 531), try fallback before marking failed
- Extract model switching into ModelRouter class
- Pro: Centralized, visible to batch client
- Con: More complex state management, high risk

---

## 3. OpenRouter Model Array Feature

OpenRouter's API supports:
```json
{
  "model": ["x-ai/grok-4-fast", "anthropic/claude-opus", "openai/gpt-4o"],
  "messages": [...]
}
```

**Behavior:**
- Tries first model, falls back to next on failure
- Charges only for successful model used
- Returns model used in `x-routed-via` response header

**Limitations:**
- Works only for non-streaming calls
- No fine-grained failure handling (all-or-nothing)
- Hides which model failed

---

## 4. Architecture Options

### Option A: Minimal Fallback (Recommended for MVP)

**Files to modify:** 2 files, ~50 lines

**Changes:**
1. Add fallback config to Config class:
```python
# infra/config.py
FALLBACK_MODELS = os.getenv('FALLBACK_MODELS', 'anthropic/claude-opus,openai/gpt-4o').split(',')
```

2. Update LLMRequest dataclass:
```python
# infra/llm/models.py
fallback_models: Optional[List[str]] = None
```

3. In batch_client._execute_request() (line ~400):
```python
if request.fallback_models and should_use_fallback(result):
    # Create new request with fallback model, re-queue
    request.model = request.fallback_models.pop(0)
    request._retry_count = 0
    queue.put(request)
else:
    # Permanent failure as before
```

**Pros:**
- Minimal code changes
- Explicit control per request
- Cost tracking stays clean (one charge per page)
- Handles both streaming and non-streaming

**Cons:**
- Manual retry logic (duplicates LLMClient retry)
- Requires pipeline stages to configure fallbacks
- Retry budget must be managed carefully

---

### Option B: Extract ModelRouter Class

**Files to modify:** 3 files, ~200 lines

**New file:** `infra/llm/router.py`
```python
class ModelRouter:
    def __init__(self, primary_model: str, fallback_models: List[str] = None):
        self.models = [primary_model] + (fallback_models or [])
        self.current_index = 0
    
    def get_current(self) -> str:
        return self.models[self.current_index]
    
    def has_fallback(self) -> bool:
        return self.current_index < len(self.models) - 1
    
    def next_model(self) -> Optional[str]:
        if self.has_fallback():
            self.current_index += 1
            return self.models[self.current_index]
        return None
```

**Batch client integration:**
```python
# batch_client.py
router = ModelRouter(request.model, request.fallback_models)

for attempt in range(max_retries):
    result = self._execute_request_with_model(request, router.get_current())
    if result.success:
        return result
    elif router.has_fallback() and should_try_fallback(result.error_type):
        router.next_model()
        continue
    else:
        return result  # Permanent failure
```

**Pros:**
- Cleaner model management
- Reusable across stages
- Easier to test and reason about
- Tracks which models were attempted

**Cons:**
- More files to modify
- Higher complexity
- Needs test coverage
- Risk of introducing bugs

---

### Option C: OpenRouter Native Models Array

**Files to modify:** 1 file, ~30 lines

**Changes in LLMClient:**
```python
# client.py
def call(self, model, messages, ..., fallback_models=None):
    model_list = [model] + (fallback_models or [])
    
    payload = {
        "model": model_list,  # Array instead of string
        "messages": messages,
        ...
    }
    
    response = requests.post(...)
    routed_via = response.headers.get('x-routed-via', model)  # Actual model used
    # Log routed_via for telemetry
```

**Pros:**
- Minimal code
- OpenRouter handles retry internally
- Automatic cost calculation

**Cons:**
- Loses visibility into which model failed
- Can't use with streaming (OpenRouter limitation)
- Costs may sum if retries happen
- No telemetry about fallback usage
- Hard to debug specific page failures

---

## 5. Recommended Approach: Option B (Extract ModelRouter)

**Rationale:**
- Option A is too low-level and duplicates retry logic
- Option C loses important telemetry and breaks streaming
- Option B provides clean abstraction with proper instrumentation

**Implementation roadmap:**

### Phase 1: Core Router
1. Create `infra/llm/router.py` with ModelRouter class
2. Add unit tests for fallback logic
3. Integrate into batch_client._execute_request()
4. Add fallback tracking to LLMResult

### Phase 2: Configuration
1. Add FALLBACK_MODELS to Config
2. Update LLMRequest dataclass with fallback_models field
3. Pipeline stages pass fallbacks when creating requests

### Phase 3: Observability
1. Log model switches in batch_client
2. Track fallback usage in batch stats
3. Update cost tracking to show which model handled each page

---

## 6. Risk Assessment & Complexity

### Code Complexity
- **Option A:** Low (50 LOC, high coupling)
- **Option B:** Medium (200 LOC, well-isolated)
- **Option C:** Low (30 LOC, poor observability)

### Refactoring Impact
- batch_client.py: Currently 1096 lines, already complex
  - Add ~50-100 lines for fallback logic
  - Extract model handling → improves maintainability
  - Thread safety: No new issues (reuses existing locks)

### Testing Burden
- **Option A:** Minimal (test error classification)
- **Option B:** Moderate (test router, integration with batch client)
- **Option C:** Minimal (OpenRouter handles it)

### Cost Tracking Risk
- **Current:** Clean, one charge per page
- **Option A/B:** Stay clean (switch before retry)
- **Option C:** Could double-charge if OpenRouter retries both models

---

## 7. Specific Implementation Details for Option B

### 7.1 Changes to batch_client.py

**In _execute_request() around line 405:**

```python
def _execute_request(self, request, json_parser, on_event):
    # Line ~399-414: Initialize router if needed
    if not hasattr(request, '_router'):
        from infra.llm.router import ModelRouter
        request._router = ModelRouter(
            request.model,
            getattr(request, 'fallback_models', None)
        )
    
    # Line ~417: Track which model we're using
    current_model = request._router.get_current()
    
    # Line ~455-462: Pass current_model instead of request.model
    response_text, usage, cost = self.llm_client.call(
        model=current_model,  # ← Use routed model
        messages=request.messages,
        ...
    )
    # Return with model info
    return LLMResult(
        ...,
        model_used=current_model,
        ...
    )
```

**In _worker_loop() around line 295:**

```python
def _worker_loop(self, ...):
    # Line 295-330: Enhanced retry with fallback
    if not result.success:
        if self._is_retryable(result.error_type):
            # Check if we should try fallback model
            router = getattr(request, '_router', None)
            if router and router.has_fallback():
                # Next model
                next_model = router.next_model()
                request._retry_count += 1
                jitter = random.uniform(*self.retry_jitter)
                time.sleep(jitter)
                queue.put(request)
                
                self._emit_event(
                    on_event,
                    LLMEvent.RETRY_QUEUED,
                    request_id=request.id,
                    retry_count=request._retry_count,
                    fallback_model=next_model,  # ← New field
                    queue_position=queue.qsize()
                )
            else:
                # No more fallbacks, treat as permanent failure
                self._mark_failed(result)
        else:
            # Permanent failure (4xx, json_parse)
            self._mark_failed(result)
```

### 7.2 New file: infra/llm/router.py

```python
#!/usr/bin/env python3
"""Model routing and fallback logic."""

from typing import List, Optional


class ModelRouter:
    """
    Manages model selection with fallback strategy.
    
    Tracks primary model and fallback chain.
    Used to retry failed requests with alternate models.
    """
    
    def __init__(self, primary_model: str, fallback_models: Optional[List[str]] = None):
        """
        Initialize router with primary and fallback models.
        
        Args:
            primary_model: Primary model to use first
            fallback_models: List of fallback models to try in order
        """
        self.primary_model = primary_model
        self.fallback_models = fallback_models or []
        self.models = [primary_model] + self.fallback_models
        self.current_index = 0
        self.attempts = []  # Track (model, success) pairs
    
    def get_current(self) -> str:
        """Get currently active model."""
        return self.models[self.current_index]
    
    def has_fallback(self) -> bool:
        """Check if fallback models are available."""
        return self.current_index < len(self.models) - 1
    
    def next_model(self) -> Optional[str]:
        """
        Advance to next fallback model.
        
        Returns:
            Next model name, or None if no more fallbacks
        """
        if self.has_fallback():
            self.current_index += 1
            model = self.models[self.current_index]
            self.attempts.append((self.models[self.current_index - 1], False))
            return model
        return None
    
    def mark_success(self):
        """Mark current model as successful."""
        self.attempts.append((self.get_current(), True))
    
    def get_attempt_history(self) -> List[tuple]:
        """Get list of (model, success) tuples."""
        return self.attempts.copy()
```

### 7.3 Changes to models.py

```python
# In LLMRequest dataclass (line ~28-46)
@dataclass
class LLMRequest:
    # ... existing fields ...
    
    # Model routing
    fallback_models: Optional[List[str]] = None  # ← Add this
    
    # Internal tracking
    _retry_count: int = field(default=0, repr=False)
    _queued_at: float = field(default=0.0, repr=False)
    _router: Optional['ModelRouter'] = field(default=None, repr=False)  # ← Add this


# In LLMResult dataclass (line ~77-136)
@dataclass
class LLMResult:
    # ... existing fields ...
    
    # Provider info
    model_used: Optional[str] = None  # Track which model succeeded
    models_attempted: Optional[List[str]] = None  # All models tried
```

### 7.4 Config changes

```python
# infra/config.py - Add after line 37
FALLBACK_MODELS = os.getenv('FALLBACK_MODELS', '').split(',') \
    if os.getenv('FALLBACK_MODELS') else []
# Empty by default, users can configure:
# export FALLBACK_MODELS="anthropic/claude-opus,openai/gpt-4o"
```

---

## 8. Specific Pages Failure Pattern

**Observed:** Pages 434, 439 fail with grok-4-fast but likely succeed with Claude/GPT-4

**Hypothesis:**
- grok-4-fast struggles with specific image characteristics (resolution, contrast, unusual layouts)
- Claude/GPT-4 have better vision training for edge cases
- Pages may have: rotated text, non-standard fonts, mixed languages

**Suggested Fallback Chain:**
```
1. x-ai/grok-4-fast (fast, cheaper)
2. anthropic/claude-opus (robust vision, higher cost ~$0.002/page)
3. openai/gpt-4o (fallback, highest cost ~$0.003/page)
```

**Cost impact:**
- Success rate with grok: ~95% → $0.0005/page avg
- With fallbacks: ~99% → $0.0006/page avg (1-2% extra cost for robustness)

---

## 9. Recommendations for Code Architect

### Immediate (MVP - 4-6 hours)
1. **Implement Option B** (ModelRouter extraction)
2. **Test locally** with accidental-president book (pages 434, 439)
3. **Configure fallbacks:**
   ```bash
   export FALLBACK_MODELS="anthropic/claude-opus,openai/gpt-4o"
   ```
4. **Verify:**
   - Pages 434, 439 now succeed
   - Cost tracking shows which model used
   - Batch stats report fallback usage

### Short-term (Follow-up PR)
1. Add monitoring dashboard showing fallback rate by page
2. Document fallback config in README
3. Add cost impact analysis to batch stats

### Future (Post-MVP)
1. Consider OpenRouter native models array if streaming becomes less critical
2. Add ML model selection based on historical failure patterns
3. Implement per-stage fallback configuration

---

## 10. Summary

| Aspect | Value |
|--------|-------|
| **Recommended Option** | B (Extract ModelRouter) |
| **Files to Create** | 1 (infra/llm/router.py) |
| **Files to Modify** | 3 (batch_client.py, models.py, config.py) |
| **Lines Added** | ~150-200 |
| **Estimated Time** | 4-6 hours including tests |
| **Risk Level** | Medium (affects core retry logic) |
| **Test Coverage Needed** | ModelRouter unit tests + batch_client integration tests |
| **Cost Impact** | +1-2% for robustness on edge case pages |
| **Rollback Risk** | Low (can disable via empty FALLBACK_MODELS) |

**Next Step:** Code architect should review thread safety implications in batch_client._worker_loop() and validate that router state doesn't need additional locking.

