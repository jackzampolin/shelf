# LLM Client Patterns

**Purpose**: Define standard patterns for LLM API calls with structured outputs, retry logic, and cost tracking.

---

## Overview

The `LLMClient` class provides centralized OpenRouter API access across all pipeline stages. It emphasizes:

- **Structured Outputs** - Native JSON schema enforcement via OpenRouter
- **Reliability** - Automatic retries with exponential backoff
- **Cost Transparency** - Returns cost per call for stage-level tracking
- **Vision Support** - Multimodal models with image inputs
- **Thread Safety** - Safe for parallel execution
- **Defensive Programming** - Graceful error handling with fallbacks

**Core principle:** All LLM calls go through `LLMClient`. No direct API calls (ensures consistent error handling, cost tracking, and retry logic).

---

## 1. Client Initialization

### 1.1 Standard Pattern

Every stage creates an LLM client:

```python
from llm_client import LLMClient

self.llm_client = LLMClient(
    site_url=Config.OPEN_ROUTER_SITE_URL,
    site_name=Config.OPEN_ROUTER_SITE_NAME
)
```

**What initialization does:**
- Loads API key from environment (`OPEN_ROUTER_API_KEY` or `OPENROUTER_API_KEY`)
- Initializes `CostCalculator` for dynamic pricing
- Sets OpenRouter tracking headers

**See implementation:**
- `llm_client.py:37-59`

### 1.2 Initialization Principles

**Principle: Fail Fast on Missing API Key**

Raise `ValueError` immediately if no API key found:
```python
if not self.api_key:
    raise ValueError("No OpenRouter API key found in environment")
```

**Why fail fast?**
- Clear error message (not mysterious failure later)
- Fails before any processing starts
- User knows exactly what to fix

**Principle: Dynamic Pricing with Cache**

Use `CostCalculator` with 24-hour pricing cache:
- Fetches latest per-token pricing from OpenRouter
- Caches for 24 hours (pricing rarely changes)
- Enables accurate cost reporting per call

**Why dynamic pricing?**
- OpenRouter pricing changes occasionally
- Different models have different costs
- Vision models charge per image
- Client returns accurate costs for stage tracking

**Principle: Singleton Pattern for Convenience**

Module-level `call_llm()` function creates client internally:
```python
def call_llm(model, system_prompt, user_prompt, **kwargs):
    client = LLMClient()
    return client.simple_call(model, system_prompt, user_prompt, **kwargs)
```

**When to use:**
- Quick one-off calls (tools, utilities)
- Scripts that don't need persistent client
- Testing with minimal boilerplate

**When NOT to use:**
- Pipeline stages (create once, reuse for all pages)
- High-volume parallel calls (overhead of client creation)

**See implementations:**
- `llm_client.py:37-59` (initialization)
- `llm_client.py:389-416` (convenience function)

---

## 2. Making LLM Calls

### 2.1 Core Call Method

Standard call pattern:

```python
response, usage, cost = self.llm_client.call(
    model=Config.CORRECT_MODEL,
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ],
    temperature=0.0,
    timeout=120,
    max_retries=3
)
```

**Returns:**
- `response` (str): LLM response text
- `usage` (dict): Token counts (`prompt_tokens`, `completion_tokens`)
- `cost` (float): Cost in USD for this call

**Note:** Client **returns** cost but does NOT accumulate. Stages track cumulative costs in their own statistics.

**See implementation:**
- `llm_client.py:61-144` (call method)

### 2.2 Call Method Principles

**Principle: Low Temperature for Structured Tasks**

Use `temperature=0.0` (deterministic) for:
- Error detection (Agent 1)
- Verification (Agent 3)
- Structure extraction
- Any task requiring consistent format

Use `temperature=0.1-0.3` for:
- Quality assessment (some flexibility needed)
- Subjective evaluation tasks

**Why low temperature?**
- Structured outputs need consistency
- Schema compliance benefits from predictable responses
- Reduces variability in output format

**Principle: Configurable Timeouts**

Default: 120 seconds (2 minutes)
Override for specific needs:
- Structure agents: 300s (5 minutes for 10-page batches)
- Quality review: 300s (long assessments)
- Quick corrections: 60s

**Why configurable?**
- Different tasks have different processing times
- Balance between patience and early failure detection
- Prevents indefinite hangs

**Principle: Return Cost (Don't Accumulate)**

Client always returns `(response, usage, cost)` but **never accumulates**:

```python
# CORRECT: Client calculates and returns
cost = self.cost_calculator.calculate_cost(model, prompt_tokens, completion_tokens, ...)
return response, usage, cost

# Stage accumulates separately
response, usage, cost = self.llm_client.call(...)
with self.stats_lock:
    self.stats['total_cost_usd'] += cost  # Stage owns accumulation
```

**Why client doesn't accumulate?**
- Client is stateless (thread-safe)
- Each stage owns its own cost tracking
- Stages may be run independently or together
- Clear separation of concerns

**See implementations:**
- `llm_client.py:61-144` (call method returns cost)
- `pipeline/correct.py` (stage accumulates costs)

---

## 3. Structured Outputs with JSON Schema

### 3.1 Schema-Based Calls

Primary pattern for all structured responses:

```python
# Define output schema
response_schema = {
    "type": "object",
    "required": ["page_number", "total_errors_found", "errors"],
    "properties": {
        "page_number": {"type": "integer", "minimum": 1},
        "total_errors_found": {"type": "integer", "minimum": 0},
        "errors": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["error_id", "location", "original_text", "error_type", "confidence"],
                "properties": {
                    "error_id": {"type": "integer", "minimum": 1},
                    "location": {"type": "string"},
                    "original_text": {"type": "string"},
                    "error_type": {
                        "type": "string",
                        "enum": ["character_substitution", "spacing", "hyphenation", "artifact", "typo"]
                    },
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "suggested_correction": {"type": "string"}
                },
                "additionalProperties": false
            }
        }
    },
    "additionalProperties": false
}

# Call with schema
result, usage, cost = self.llm_client.call_with_schema(
    model=Config.CORRECT_MODEL,
    messages=[...],
    response_schema=response_schema,
    temperature=0.0
)

# Result is guaranteed valid dict - use directly
page_number = result['page_number']  # Type-safe
errors = result['errors']  # Always present (required field)
```

**Returns:**
- `result` (dict): Parsed JSON dictionary validated against schema
- `usage` (dict): Token counts
- `cost` (float): Cost for this call

**See implementation:**
- `llm_client.py` (call_with_schema method)

### 3.2 Structured Output Principles

**Principle: Schema as Contract**

Schema defines stage output contract:
- Input expectations (what LLM produces)
- Output validation (what checkpoint verifies)
- Documentation (what next stage expects)
- Single source of truth

**Why schema as contract?**
- Clear boundaries between stages
- Type safety (no guessing at runtime)
- Refactoring confidence (change internals, schema stays same)
- Testing clarity (fixtures match schema)

**Principle: Co-locate Schemas with Stages**

Store schemas in stage modules:
```python
# pipeline/correct.py
AGENT1_SCHEMA = {
    "type": "object",
    "properties": {
        "page_number": {"type": "integer"},
        "errors": {"type": "array", "items": {...}}
    },
    "required": ["page_number", "errors"],
    "additionalProperties": false
}

class StructuredPageCorrector:
    def agent1_detect_errors(self, ...):
        result, usage, cost = self.llm_client.call_with_schema(
            model=self.model,
            messages=[...],
            response_schema=AGENT1_SCHEMA
        )
```

**Why co-locate?**
- Schemas live with code that uses them
- Easy to find and update
- Clear which schema belongs to which agent
- No central schema file bottleneck

**Principle: Use `strict: true` Mode**

Always set `strict: true` in schema request:
```python
# In call_with_schema implementation:
response_format = {
    "type": "json_schema",
    "json_schema": {
        "name": "agent1_errors",
        "schema": response_schema,
        "strict": True  # <-- Enforce exact match
    }
}
```

**Why strict mode?**
- Guarantees schema compliance
- No additional properties (prevents LLM improvisation)
- Consistent structure across all calls
- Reduces validation overhead

**Principle: Fallback for Unsupported Models**

Not all models support structured outputs:
- OpenAI models (GPT-4o and later): ✅ Supported
- Fireworks models: ✅ Supported
- Some providers: ❌ Not supported

**Implementation strategy:**
```python
def call_with_schema(self, model, messages, response_schema, **kwargs):
    if self._model_supports_structured_outputs(model):
        # Use native structured outputs
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"schema": response_schema, "strict": True}
        }
        response, usage, cost = self._call_non_streaming(...)
        return json.loads(response), usage, cost
    else:
        # Fallback: Include schema in prompt + validate after
        messages = self._add_schema_to_prompt(messages, response_schema)
        response, usage, cost = self.call(model, messages, **kwargs)
        parsed = self._parse_and_validate_json(response, response_schema)
        return parsed, usage, cost
```

**Principle: No Manual JSON Cleanup**

Structured outputs guarantee valid JSON:
- No trailing commas
- No missing commas
- No markdown code blocks
- No type confusion (integers are integers, not strings)

**What to remove:**
```python
# OLD: Manual JSON extraction (DEPRECATED)
json_text = self.extract_json(response)
fixed_text = re.sub(r',(\s*[}\]])', r'\1', json_text)  # NO LONGER NEEDED

# NEW: Trust structured output
result, usage, cost = self.llm_client.call_with_schema(...)
# Result is guaranteed valid - use directly
```

**Principle: Type Enforcement**

Schema enforces types automatically:

```python
# Schema definition:
"scan_page": {"type": "integer", "minimum": 1}

# OLD problem: LLM sometimes returned
"scan_page": "PAGE 77"  # String instead of int

# NEW: Structured outputs enforce
result['scan_page']  # Always int, never string
```

**Principle: Enum Validation**

Use enums for constrained values:

```python
"confidence": {
    "type": "string",
    "enum": ["high", "medium", "low"]
}

# OLD problem: LLM returned variations
"confidence": "High"  # Wrong case
"confidence": "very high"  # Invalid value

# NEW: Only enum values allowed
result['confidence']  # Always one of: "high", "medium", "low"
```

**See OpenRouter docs:**
- https://openrouter.ai/docs/features/structured-outputs

**See implementations:**
- `llm_client.py` (call_with_schema implementation)
- `pipeline/correct.py` (Agent 1 and Agent 3 schemas)
- `pipeline/structure/agents/` (extraction agent schemas)

---

## 4. Automatic Retry Logic

### 4.1 Server Error Retries

Automatic retry on 5xx errors with exponential backoff:

**Retry schedule:**
- Attempt 1: Immediate
- Attempt 2: Wait 1s
- Attempt 3: Wait 2s
- Attempt 4: Wait 4s (max_retries=3 by default)

**What triggers retry:**
- HTTP 500-599 status codes (server errors)
- Timeout exceptions (`requests.exceptions.Timeout`)

**What does NOT retry:**
- HTTP 4xx status codes (client errors - fix request first)
- Schema validation errors (handled by fallback logic)

**See implementation:**
- `llm_client.py:113-143` (retry loop)

### 4.2 Retry Principles

**Principle: Exponential Backoff**

```python
delay = 2 ** attempt  # 1s, 2s, 4s
time.sleep(delay)
```

**Why exponential?**
- Gives server time to recover
- Reduces thundering herd (parallel workers don't all retry at once)
- Standard practice for distributed systems

**Principle: Don't Retry Client Errors**

```python
except requests.exceptions.HTTPError as e:
    if e.response.status_code >= 500:
        # Retry server errors
        ...
    else:
        # Don't retry client errors (4xx)
        raise
```

**Why not retry 4xx?**
- Client error means request is malformed
- Retrying won't fix the problem
- Indicates code bug (invalid API key, bad request format)
- Fail fast so developer can fix root cause

**Principle: User Visibility**

```python
print(f"  ⚠️  Server error (attempt {attempt + 1}/{max_retries}), retrying in {delay}s...")
```

**Why print?**
- Long-running stages need visibility
- User knows system is working (not hung)
- Helps diagnose chronic API issues

**Principle: Accumulate Retry Costs**

If retries happen, accumulate their costs:

```python
# In retry loop
total_cost = 0.0
for attempt in range(max_retries):
    try:
        response, usage, cost = self._call_non_streaming(...)
        total_cost += cost
        return response, usage, total_cost  # Return accumulated
    except requests.exceptions.HTTPError as e:
        total_cost += cost  # Track failed attempts too
        if should_retry:
            continue
```

**Why accumulate retry costs?**
- User pays for all API calls (successes + failures)
- Accurate cost reporting
- Helps identify expensive retry patterns

**See implementations:**
- `llm_client.py:113-143` (retry implementation)
- All pipeline stages benefit automatically

---

## 5. Vision Model Support

### 5.1 Image Handling

For vision models (metadata extraction, quality assessment):

```python
# Convert PDF pages to images
images = [convert_pdf_page_to_image(page) for page in sample_pages]

# Build multimodal content
content = [{"type": "text", "text": prompt}]
for img_data in images:
    content.append({
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{img_data}"}
    })

response, usage, cost = self.llm_client.call(
    model=Config.VISION_MODEL,  # Claude Sonnet 4.5 (vision capable)
    messages=[{"role": "user", "content": content}],
    temperature=0.0,
    images=images  # For cost tracking
)
```

**See implementations:**
- `llm_client.py:244-294` (image handling)
- `tools/ingest.py` (book identification with vision)
- `tools/discover.py` (metadata extraction from PDFs)

### 5.2 Vision Model Principles

**Principle: Multimodal Content Format**

Use OpenAI-style content arrays:
```python
content = [
    {"type": "text", "text": "Your prompt"},
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
]
```

**Why this format?**
- OpenRouter standardizes on OpenAI format
- Works across all vision providers
- Can mix text and images freely
- Order matters (text before images = instruction context)

**Principle: Base64 Image Encoding**

Always encode images as base64 data URLs:
```python
img_b64 = base64.b64encode(img_bytes).decode('utf-8')
url = f"data:image/png;base64,{img_b64}"
```

**Why base64?**
- No need for image hosting
- Works in single API call
- Consistent with multimodal content format
- Simpler than URL references

**Principle: Image Cost Tracking**

Vision models charge per image:
```python
cost = self.cost_calculator.calculate_cost(
    model,
    prompt_tokens,
    completion_tokens,
    num_images=len(images)  # <-- Track image count
)
```

**Why track images?**
- Significant cost factor (1 image ≈ 1000 tokens)
- Client returns accurate cost including images
- Helps optimize sampling strategy

**Principle: Strategic Sampling**

Don't send all pages to vision models:
- Ingest: First 10 pages (title page, TOC, copyright)
- Discover: First 3 pages (sufficient for metadata)
- Quality review: Text-only (no images needed)

**Why sample?**
- Vision models are expensive (10x more than text-only)
- Most information is in first few pages
- Diminishing returns after sample
- Balance cost vs information gained

**See implementations:**
- `tools/ingest.py:185-234` (10-page sampling for book ID)
- `tools/discover.py:75-120` (3-page sampling for metadata)

---

## 6. Cost Tracking

### 6.1 Client Returns Costs (Doesn't Accumulate)

Client calculates and returns cost per call:

```python
# Client implementation
def call(self, model, messages, ...):
    response = # ... API call ...
    usage = result.get('usage', {})

    # Calculate cost for THIS call only
    cost = self.cost_calculator.calculate_cost(
        model,
        usage.get('prompt_tokens', 0),
        usage.get('completion_tokens', 0),
        num_images=len(images) if images else 0
    )

    return response, usage, cost  # Return cost, don't store
```

**Stage accumulates separately:**

```python
# Stage implementation
response, usage, cost = self.llm_client.call(...)

# Stage owns cost tracking
with self.stats_lock:
    self.stats['total_cost_usd'] += cost
    self.stats['pages_processed'] += 1
```

**See implementations:**
- `llm_client.py:167-173` (cost calculation)
- `pricing.py` (CostCalculator class)
- `pipeline/correct.py` (stage cost accumulation)

### 6.2 Cost Tracking Principles

**Principle: Client is Stateless**

Client **never** stores costs:
```python
# CORRECT: Return cost
return response, usage, cost

# WRONG: Don't accumulate in client
# self.total_cost += cost  # NO - breaks thread safety
```

**Why stateless?**
- Thread-safe (multiple parallel calls)
- Client reusable across stages
- Each stage owns its cost tracking
- Clear separation of concerns

**Principle: Dynamic Pricing with 24h Cache**

Fetch pricing from OpenRouter API:
```python
class CostCalculator:
    def __init__(self):
        self.pricing_cache = PricingCache()  # 24-hour TTL

    def calculate_cost(self, model_id, prompt_tokens, completion_tokens, ...):
        pricing = self.pricing_cache.get_model_pricing(model_id)
        return (prompt_tokens * pricing['prompt']) +
               (completion_tokens * pricing['completion']) +
               (num_images * pricing['image'])
```

**Why dynamic pricing?**
- OpenRouter pricing changes occasionally
- New models have different rates
- Accurate cost reporting requires current rates

**Why 24-hour cache?**
- Pricing rarely changes (safe to cache)
- Reduces API calls (one fetch per day)
- Balances accuracy vs performance

**Principle: Stages Accumulate with Thread Safety**

Stages track cumulative costs:
```python
class Stage:
    def __init__(self):
        self.stats = {'total_cost_usd': 0.0}
        self.stats_lock = threading.Lock()

    def process_page(self, page_num):
        response, usage, cost = self.llm_client.call(...)

        # Thread-safe accumulation
        with self.stats_lock:
            self.stats['total_cost_usd'] += cost
```

**Why stage accumulation?**
- Client is stateless (doesn't track)
- Each stage needs its own total
- Checkpoint saves accumulated cost
- Resume runs add to existing cost

**Principle: Include Costs in Checkpoint Metadata**

Save accumulated cost for resume:
```python
self.checkpoint.mark_stage_complete(metadata={
    "model": self.model,
    "pages_processed": pages_processed,
    "total_cost_usd": self.stats['total_cost_usd']  # Cumulative across all runs
})
```

**Why in checkpoint?**
- Persists across sessions
- Resume runs don't reset cost
- Accurate total for book processing
- Historical cost tracking

**Typical costs (447-page book):**
- OCR: $0 (Tesseract - local)
- Correction: $10 (gpt-4o-mini, 30 workers)
- Fix: $1 (Claude Sonnet 4.5, targeted)
- Structure: $0.50 (gpt-4o-mini or Claude)
- **Total: ~$12/book**

**See implementations:**
- `pricing.py` (CostCalculator implementation)
- `checkpoint.py` (cost in metadata)
- All pipeline stages (cost accumulation)

---

## 7. Thread Safety

### 7.1 Thread-Safe Patterns

LLMClient is thread-safe for parallel execution:

**Client state:**
- `api_key`, `base_url`, `cost_calculator` - Read-only after init
- No shared mutable state across calls
- Each call is independent

**Stage statistics (separate from client):**
```python
class CorrectStage:
    def __init__(self, ...):
        self.stats = {"total_cost_usd": 0.0, "pages_processed": 0}
        self.stats_lock = threading.Lock()

    def process_page(self, page_num):
        # Client call (thread-safe)
        response, usage, cost = self.llm_client.call(...)

        # Stage accumulation (thread-safe with lock)
        with self.stats_lock:
            self.stats['total_cost_usd'] += cost
            self.stats['pages_processed'] += 1
```

**See implementations:**
- `llm_client.py` (stateless client)
- `pipeline/correct.py:56-110` (thread-safe stage statistics)

### 7.2 Thread Safety Principles

**Principle: Client is Stateless**

LLMClient has no per-call state:
- Each `call()` is independent
- No shared buffers or counters
- Safe to call from multiple threads

**Why stateless?**
- Simple concurrency (no locks needed in client)
- Parallel workers can share client
- No race conditions

**Principle: Stages Own Statistics**

Cost tracking lives in stage, not client:
```python
# CORRECT: Stage tracks costs
with self.stats_lock:
    self.stats['total_cost_usd'] += cost

# WRONG: Don't accumulate in client
# self.llm_client.total_cost += cost  # NOT THREAD-SAFE
```

**Why stage-owned?**
- Each stage tracks its own costs
- Client is reusable across stages
- Clear ownership (stage knows its costs)

**Principle: Lock Before Update**

All shared state updates inside lock:
```python
# Thread-safe pattern
with self.stats_lock:
    self.stats['count'] += 1
    self.stats['total'] += value

# WRONG: Race condition
self.stats['count'] += 1  # Read-modify-write not atomic
```

**Why lock?**
- Prevents race conditions
- Ensures atomic updates
- Python GIL doesn't protect compound operations

**Principle: Checkpoint Thread Safety**

CheckpointManager has internal locking:
```python
# Safe to call from parallel workers
self.checkpoint.mark_completed(page_num)
```

**Why internal locking?**
- Checkpoint updates must be atomic
- Workers don't need to coordinate
- Simplifies stage implementation

**See implementations:**
- `checkpoint.py` (internal locking)
- `pipeline/correct.py` (thread-safe stage statistics)

---

## 8. Model Selection

### 8.1 Configuration Pattern

Models configured via environment or defaults:

```python
# config/__init__.py
class Config:
    # Correction Stage (3-agent pipeline)
    CORRECT_MODEL = os.getenv('CORRECT_MODEL', 'openai/gpt-4o-mini')

    # Fix Stage (Agent 4)
    FIX_MODEL = os.getenv('FIX_MODEL', 'anthropic/claude-sonnet-4.5')

    # Structure Stage - Extract Phase
    EXTRACT_MODEL = os.getenv('EXTRACT_MODEL', 'openai/gpt-4o-mini')

    # Other stages...
```

**Note:** Config names subject to change during refactor. Use `Config.get_model_for_stage(stage_name)` method when available.

**Model usage in stages:**
```python
class CorrectStage:
    def __init__(self, ..., model: Optional[str] = None):
        # Default from config, allow override
        self.model = model or Config.CORRECT_MODEL
```

**See implementations:**
- `config/__init__.py:34-57` (model configuration)
- All pipeline stages (model initialization)

### 8.2 Model Selection Principles

**Principle: Cost vs Quality Tradeoff**

**High-volume, structured tasks** → Cheap models:
- Correction (Agent 1, 3): `gpt-4o-mini` (~$10/book)
- Structure extraction: `gpt-4o-mini` (~$0.50/book)
- Sufficient quality for structured output
- Fast throughput (high rate limits)

**Quality-critical, targeted tasks** → Premium models:
- Fix (Agent 4): `claude-sonnet-4.5` (~$1/book)
- Quality review: `claude-sonnet-4.5` (~$0.20/book)
- Better reasoning for complex corrections
- More reliable assessment

**Why mixed approach?**
- Balance total cost with output quality
- Expensive models where they matter most
- Cheap models for high-volume work
- Total cost still reasonable (~$12/book)

**Principle: Configuration with Override**

```python
# Default: Use config
stage = CorrectStage(scan_id="modest-lovelace")

# Override: Experiment with different model
stage = CorrectStage(scan_id="modest-lovelace", model="anthropic/claude-3.5-sonnet")
```

**Why allow override?**
- Testing different models (cost/quality comparison)
- Per-book optimization (historical vs modern text)
- Emergency fallback (if primary model unavailable)

**Principle: Document Model Choices**

In stage docstrings and logs:
```python
"""
Correction Stage
Uses gpt-4o-mini for cost-effective high-volume corrections.
Override with CORRECT_MODEL environment variable or model parameter.
"""

self.logger.info(f"Using model: {self.model}")
```

**Why document?**
- Explains cost/quality tradeoff
- Helps users understand charges
- Guides model selection for similar tasks

**Principle: Vision Models for Multimodal Tasks**

Use vision-capable models only when needed:
- Ingest: Vision model (Claude Sonnet 4.5) - needs to read PDF scans
- Structure: Text model (gpt-4o-mini) - already has clean text
- Quality: Text model (Claude Sonnet 4.5) - assessing text quality

**Why separate?**
- Vision models are expensive (10x more)
- Most stages work with extracted text
- Only use vision when image context needed

**See implementations:**
- `config/__init__.py:34-57` (current configuration)
- `pipeline/correct.py` (gpt-4o-mini for volume)
- `pipeline/fix.py` (Claude Sonnet for quality)

---

## 9. Error Handling

### 9.1 Graceful Degradation

Handle errors defensively at multiple levels:

**Level 1: Retry Logic** (automatic in client)
- Server errors (5xx) → Retry with backoff
- Timeouts → Retry with backoff

**Level 2: Schema Fallback** (for unsupported models)
- Native structured outputs fail → Fallback to prompt-based schema
- Parse failure → Include schema in prompt, validate after

**Level 3: Page-Level Errors** (return error status)
```python
def process_page(self, page_num):
    try:
        # ... processing ...
        return {"page": page_num, "status": "success", "cost": cost}
    except Exception as e:
        self.logger.error(f"Page {page_num} failed: {e}")
        return {"page": page_num, "status": "error", "error": str(e)}
```

**Level 4: Stage-Level Errors** (mark failed, preserve progress)
```python
try:
    self._process_all_pages(page_numbers)
    self.checkpoint.mark_stage_complete(metadata={...})
except Exception as e:
    if self.checkpoint:
        self.checkpoint.mark_stage_failed(error=str(e))
    raise
```

**See implementations:**
- `llm_client.py` (retry logic, schema fallback)
- `pipeline/correct.py` (page-level error handling)
- `pipeline/structure/__init__.py` (stage-level error handling)

### 9.2 Error Handling Principles

**Principle: Never Raise from Workers**

Parallel worker functions return error status:
```python
# CORRECT: Return error dict
def process_page_worker(page_num):
    try:
        result = process_page(page_num)
        return {"status": "success", "page": page_num}
    except Exception as e:
        return {"status": "error", "page": page_num, "error": str(e)}
```

**Why return errors?**
- Parallel executor collects all results
- One bad page doesn't stop others
- Stage can aggregate errors
- Continue processing despite failures

**Principle: Log Context with Errors**

Include page number, stage, and model:
```python
self.logger.error(
    f"Agent 1 failed on page {page_num}",
    extra={
        "page": page_num,
        "stage": "correction",
        "agent": "agent1",
        "model": self.model,
        "error": str(e)
    }
)
```

**Why rich context?**
- Debugging (which page? which agent?)
- Pattern detection (is it always page 300?)
- Model comparison (does gpt-4o-mini fail more?)

**Principle: Preserve Partial Progress**

Failed stage keeps completed pages:
```python
# Mark failed preserves completed pages in checkpoint
self.checkpoint.mark_stage_failed(error=str(e))

# Resume can continue from where it left off
remaining = self.checkpoint.get_remaining_pages(total_pages)
```

**Why preserve progress?**
- Don't waste completed work
- Resume from failure point
- Partial results still valuable
- Cost already paid for completed pages

**See implementations:**
- `pipeline/correct.py` (error handling in page worker)
- `checkpoint.py` (mark_stage_failed preserves progress)

---

## 10. Legacy: Manual JSON Extraction (Deprecated)

**Note:** This section documents legacy patterns used before structured outputs. These patterns are **deprecated** and should be replaced with `call_with_schema()`.

### 10.1 Old Extraction Pattern (Pre-Structured Outputs)

Three-tier extraction strategy (now obsolete):

**Tier 1: Remove markdown code blocks**
```python
if '```json' in text or '```' in text:
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if json_match:
        text = json_match.group(1).strip()
```

**Tier 2: Find JSON boundaries**
```python
first_brace = text.find('{')
last_brace = text.rfind('}')
if first_brace != -1 and last_brace != -1:
    text = text[first_brace:last_brace + 1]
```

**Tier 3: Fix common syntax errors**
```python
# Trailing commas before closing brackets
fixed_text = re.sub(r',(\s*[}\]])', r'\1', fixed_text)

# Missing commas between objects
fixed_text = re.sub(r'}\s*{', '},{', fixed_text)
```

**Migration path:**
- Replace all `extract_json()` calls with `call_with_schema()`
- Remove regex-based JSON fixes
- Define schemas for each agent
- Test with schema fallback for unsupported models

**See legacy implementations:**
- `pipeline/correct.py:558-619` (StructuredPageCorrector.extract_json)
- To be removed when migration complete

---

## Summary

A production-ready LLM integration:

1. ✅ Centralizes all calls through `LLMClient`
2. ✅ Uses structured outputs with JSON schema (native OpenRouter feature)
3. ✅ Automatic retry with exponential backoff (5xx, timeouts)
4. ✅ Returns costs per call (stages accumulate separately)
5. ✅ Vision model support with base64 encoding
6. ✅ Thread-safe (stateless client, stage-owned statistics)
7. ✅ Graceful error handling with schema fallback
8. ✅ Low temperature for structured tasks
9. ✅ Model selection based on cost/quality tradeoff
10. ✅ Schema-based validation eliminates manual JSON extraction

---

## Next Steps

This completes the core pipeline standards documentation:
- [01_stage_interface.md](01_stage_interface.md) - Stage patterns
- [02_checkpointing.md](02_checkpointing.md) - Resume capability
- [03_llm_client.md](03_llm_client.md) - LLM API patterns (this document)
