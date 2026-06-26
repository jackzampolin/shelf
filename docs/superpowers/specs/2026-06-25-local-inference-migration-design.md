# Local Inference Migration — Design

**Date:** 2026-06-25
**Status:** Design (umbrella spec; decomposes into sub-specs)
**Author:** Jack Zampolin + Claude

## Goal

Move the book-digitization pipeline off the OpenRouter / Mistral cloud APIs and onto
self-hosted models running on local hardware reachable over Tailscale. This round
covers the two inference surfaces that run on the **DGX Sparks**:

- **OCR** — replace Mistral OCR (`mistral-ocr-2512`) with **Chandra OCR 2** (`datalab-to/chandra-ocr-2`).
- **LLM** — replace OpenRouter (`anthropic/claude-opus-4.6`) with **Qwen3.6-35B-A3B** (MoE).

**Out of scope this round:** TTS. The RTX Pro 6000 box is currently serving production
agents; TTS stays on cloud OpenAI for now and migrates in a later round when that box
is freed. The TTS notes below are captured only so the eventual sub-spec inherits context.

## Why this is tractable

The provider layer added during the original build is already model-agnostic:

- Three interfaces — `LLMClient`, `OCRProvider`, `TTSProvider` (`internal/providers/provider.go`).
- Providers are keyed by a string `type` and built through a factory switch
  (`internal/providers/registry.go` `createLLMClient` / `createOCRProvider`).
- Nothing in job logic hardcodes "openrouter" / "mistral".
- The OpenRouter client already speaks OpenAI-compatible `/chat/completions` with tools,
  vision (base64 images), and structured-output validation + repair
  (`internal/providers/openrouter_chat.go`, `structured_output.go`). It even has an
  unused `BaseURL` field.

So the work is **additive**: new provider implementations + config wiring. OpenRouter /
Mistral / OpenAI stay registerable side-by-side, enabling per-stage A/B (local vs cloud).

## Hardware & model decisions (locked)

### LLM: Qwen3.6-35B-A3B (MoE)

Chosen over the dense `Qwen3.6-27B` and over the originally-proposed
`Qwen-AgentWorld-35B-A3B`.

- **`Qwen-AgentWorld-35B-A3B` was the wrong category.** It is a *language world model*
  that simulates an agent's environment (predicts next environment state), not a
  tool-using assistant. Its checkpoint is also LM-weights-only (text-only;
  `--language-model-only` required). Our pipeline needs the assistant side of the loop.
- **MoE over dense on the Spark.** The DGX Spark is bandwidth-bound (128GB unified
  LPDDR5x @ **273 GB/s**); decode throughput tracks active params read per token.
  - `35B-A3B` (3B active, FP8): ~3 GB/token → ~90 tok/s/stream ceiling, scales with batch.
  - `27B dense` (FP8): ~27 GB/token → ~10 tok/s/stream. ~9× slower for comparable quality.
  - The MoE preserves exactly the advantage that makes this hardware viable.
- **Capabilities.** Qwen3.6-35B-A3B is natively multimodal (text/image/video),
  Instruct-tuned, Apache 2.0, 262K context, strong agentic tool use (MCPMark 37.0,
  SWE-bench Verified 73.4%), with JSON/structured output and OpenAI-compatible tool use.
- **Target serving recipe (locked): NVFP4 on DGX Spark.** Per the vLLM Qwen3.6 recipe's
  DGX Spark / GB10 path, serve the **`nvidia/Qwen3.6-35B-A3B-NVFP4`** checkpoint:

  The full recipe command (reproduce verbatim in provisioning):

  ```
  vllm serve nvidia/Qwen3.6-35B-A3B-NVFP4 \
    --trust-remote-code \
    --kv-cache-dtype fp8 \
    --attention-backend flashinfer \
    --moe-backend marlin \
    --gpu-memory-utilization 0.4 \
    --max-model-len 262144 \
    --max-num-seqs 4 \
    --max-num-batched-tokens 8192 \
    --enable-prefix-caching \
    --speculative-config '{"method":"mtp","num_speculative_tokens":3,"moe_backend":"triton"}' \
    --load-format fastsafetensors \
    --reasoning-parser qwen3 \
    --tool-call-parser qwen3_xml \
    --enable-auto-tool-choice
  ```

  Notes that flow into the plan:
  - Parser is **`qwen3_xml`** (the Spark NVFP4 path), NOT `qwen3_coder` (generic card) or
    `hermes` (Hermes models). The served model name jobs reference is the NVFP4 repo.
  - **Requires vLLM nightly or source build** — provisioning must pin a known-good rev.
  - The recipe's `--gpu-memory-utilization 0.4` already reserves most of the GB10 for other
    workloads; co-resident Chandra gets its own budget so the two sum to <1.0. NVFP4 weights
    are ~18–20GB + Chandra ~10GB → ample KV-cache headroom on the 128GB Spark.
  - Add the thinking-disable flag for the JSON stages (see LLM sub-spec):
    `--default-chat-template-kwargs '{"enable_thinking": false}'`.
- **Payoff:** a *single* model covers every LLM stage — the text JSON-extraction stages
  **and** the image-based ToC/chapter agents — with **no agent-architecture changes**.

### OCR: Chandra OCR 2 (`datalab-to/chandra-ocr-2`)

- 5B multimodal model built on Qwen 3.5; served via `vllm serve datalab-to/chandra-ocr-2`.
- Input: images/PDFs. Output: markdown / HTML / JSON with preserved layout; handles
  tables, math, handwriting, checkboxes, 90+ languages.
- olmOCR benchmark 85.9; ~1.44 pages/sec on a single H100 (Sparks will be slower on
  prefill but acceptable; OCR is a batch/offline phase).

### Serving topology

- **spark-1** (100.74.68.88) and **spark-2** (100.86.62.91), both Linux, each a single
  GB10 GPU.
- Each Spark runs **both** `Qwen3.6-35B-A3B-NVFP4` (vLLM, ~18–20GB) **and** `chandra-ocr-2`
  (vLLM, ~10GB) co-resident — ~30GB of 128GB for weights, leaving large room for KV cache
  on both. Because both vLLM servers share one GB10 GPU, each is launched with an explicit
  `--gpu-memory-utilization` budget so their weights + KV caches fit without OOM, and the
  GPU **time-slices compute between them** during overlap.
- **OCR and LLM phases DO overlap** (corrected): metadata extraction starts once 20 pages
  are OCR-complete (`OcrThresholdForMetadata = 20`) and the ToC finder starts after 30
  consecutive front-matter pages (`ConsecutiveFrontMatterRequired = 30`), while later
  pages are still being OCR'd (`internal/jobs/process_book/job/types.go:12,29`,
  `state.go:45-75`). The overlap is partial and front-loaded — the early LLM work
  (metadata, ToC-finder) is a small number of light agents, while the heavy LLM load
  (per-entry ToC linking, structure) lands after most OCR has finished — but it is real.
  Co-residence must therefore be sized for concurrent OCR+LLM, and OCR/LLM concurrency
  (rate limits, vLLM `--max-num-seqs`) tuned so neither starves the other.
- **Fallback topology if contention degrades throughput:** role-split the Sparks —
  spark-1 = LLM only, spark-2 = OCR only. Removes contention at the cost of per-model
  redundancy and balanced load. Decide based on measured overlap throughput.
- Where both models run on both Sparks, requests are **round-robined** per model type.
  For a concurrent batch workload this beats tensor-parallel-across-Sparks: no cross-node
  interconnect penalty, fault isolation, and 2× batch slots.
- **RTX Pro 6000 box:** reserved for production agents this round; not used here.

## Integration design

### Foundation (shared)

1. **Expose endpoints in config — shape pinned as `base_urls []string`.** Add
   `BaseURLs []string` to `LLMProviderCfg` and the OCR provider config in
   `internal/config/schema.go` (a singular `base_url` may be accepted as sugar that
   appends to the list). Thread it through `ToProviderRegistryConfig`
   (`internal/config/config.go:152`), which today copies only Type/Model/APIKey/RateLimit/
   Enabled and env-resolves **only** `APIKey` — so `BaseURLs` must be added to the
   `LLMProviderConfig`/`OCRProviderConfig` conversion **and** run through `ResolveEnvVars`
   per element. This single list also serves the round-robin (next item); there is no
   separate singular-vs-list config path.
2. **Round-robin endpoints.** The provider round-robins requests across its `base_urls`
   (the two Sparks).
3. **Config-source coupling (must document + enforce).** Provider *registration* comes
   from YAML via `ConfigManager.Get().ToProviderRegistryConfig()`
   (`internal/server/server.go:117`), while jobs *select* providers by name from the
   DefraDB settings store — `defaults.llm_provider` and `defaults.ocr_providers`
   (`internal/jobcfg/builder.go:43,48`). These are two different sources: a local provider
   must be **enabled in YAML** (so it registers) **and** named in the DB `defaults.*`
   settings (so jobs route to it). If they diverge, the scheduler routes work to an
   unregistered pool. The foundation work includes setting both consistently and
   documenting the coupling (ideally a startup assertion that every `defaults.*` provider
   name resolves to a registered provider).
4. **Optional auth.** Registration currently skips any enabled provider with an empty
   `APIKey` (`internal/providers/registry.go:322` and `:423`). Local vLLM needs no real
   key, so either (a) configure a static placeholder token (simplest, config-only, no
   code change — recommended for v1), or (b) relax the registration guard to permit an
   empty key for local provider types. Pick (a) unless we later want true keyless local
   registration.
5. **Health checks / fail-fast.** Startup wiring goes through `scheduler.InitFromRegistry`
   (`internal/server/server.go:295`), which does **not** run provider health checks, and
   even when enabled a failure only warns. For local inference a down Spark means the
   whole pipeline stalls (no cloud fallback), so add an explicit startup probe of each
   configured Spark endpoint (vLLM `/health` or `/v1/models`) that fails loudly — decide
   fail-fast vs. warn-and-degrade. Implement `HealthCheck` per provider accordingly.
6. **Cost semantics.** Local inference has ~zero marginal dollar cost. Record
   `cost_usd = 0` for local providers and keep the existing token/latency metrics as the
   meaningful signal (tokens/sec, latency, eventually GPU utilization). Capture this as a
   short ADR note since it inverts ADR-002's per-call-dollar premise.

### LLM sub-spec — `openai-compat` (vLLM) provider

- New provider `type: "openai-compat"` (or `"vllm"`) in `createLLMClient`. It **shares the
  OpenAI-compatible request/response types and the structured-output validation+repair
  helpers** from the OpenRouter implementation, but is its **own client** — it must not
  reuse OpenRouter's identity-specific behavior: OpenRouter health-checks `/auth/key`
  (`openrouter.go:99`), sets OpenRouter referer/title headers (`openrouter_http.go:45`),
  requests `usage.include`, and parses OpenRouter cost fields (`openrouter_chat.go`). The
  openai-compat client owns: health (`/v1/models` or `/health`), auth (optional/static),
  headers (none special), and cost (`= 0`). Refactor the shared types/helpers out of the
  OpenRouter package so both clients depend on them.
- Config: `base_urls` (the two Sparks), `model: nvidia/Qwen3.6-35B-A3B-NVFP4` (see
  Target serving recipe), static placeholder `api_key`, rate limit, concurrency.
- **Thinking mode decision.** Qwen3.6 defaults to *thinking* mode, but the structured-JSON
  stages cap output low (e.g. metadata `MaxTokens: 2048`, `internal/prompts/metadata/
  workunit.go:68`) and expect clean JSON — thinking traces would consume the token budget
  and pollute parsing. `ChatRequest` has no `extra_body`/`chat_template_kwargs` today
  (`workunit.go:61-68`). **v1: disable thinking at the server** via
  `--default-chat-template-kwargs '{"enable_thinking": false}'` (no code change, applies to
  all stages). If a stage (e.g. a ToC vision agent) later benefits from reasoning, add an
  optional `chat_template_kwargs`/`extra_body` field to `ChatRequest` and set it
  per-request — deferred until a stage demonstrably needs it.
- **Validation gate:** before wiring all stages, run one stage end-to-end (recommend
  `metadata` — text + JSON schema, no vision) against a Spark to confirm structured
  output + repair behaves. Then validate one vision agent stage (`toc_finder`).

### OCR sub-spec — `chandra` provider

- New provider `type: "chandra"` implementing `OCRProvider.ProcessImage`. Sends the page
  image to the Chandra vLLM endpoint with an OCR prompt and parses the response.
- **Output-contract decision: markdown-first.** Downstream stages consume the OCR
  markdown today. The Mistral-specific extras (native header/footer extraction, image
  bounding-box metadata) become *optional* — Chandra can emit structured JSON+layout if a
  later need arises, but the first cut targets markdown parity with the Mistral path.
- Validate the exact Chandra serving API surface during implementation (OpenAI-compatible
  chat-with-image vs. datalab's own server/CLI) and adapt the client accordingly.

### TTS (deferred — captured for the future sub-spec)

- The OpenAI TTS client (`internal/providers/openai_tts.go:28`) already has a `BaseURL`
  field, but `createTTSProvider` (`internal/providers/registry.go:521`) does not yet pass
  it through from config — so a self-hosted OpenAI-compatible `/v1/audio/speech` target
  needs the same `base_urls` config wiring as the LLM/OCR providers, not just config.
- Candidate models to bake off on the RTX Pro 6000 when available: **Qwen3-TTS**
  (Apache 2.0, long-form, same ecosystem), **Fish Speech / S2** (top voice cloning),
  **Hume TADA** (long-form up to 700s/pass), Dia, XTTS-v2.

## Decomposition & build order

Each numbered item below becomes its own spec → plan → implementation cycle.

1. **Foundation** — `base_urls` config + round-robin + optional-auth + fail-fast health
   probes + cost=0 semantics.
2. **LLM sub-spec** — `openai-compat` provider; validate `metadata` then `toc_finder`
   against a Spark before enabling all stages.
3. **OCR sub-spec** — `chandra` provider + serving; markdown parity with Mistral path.
4. **TTS sub-spec** — *later round*, once the RTX Pro 6000 box is freed.

## Risks & open items

- **Quality parity vs. cloud.** Qwen3.6-35B-A3B replacing Claude Opus, and Chandra
  replacing Mistral OCR. Keep cloud providers registerable for A/B; spot-check a known
  book through both before cutting over.
- **vLLM tool-calling fidelity.** The `qwen3_xml` tool-call parser (+ `qwen3` reasoning
  parser) must reliably produce the tool calls the agents expect. Covered by the
  `toc_finder` validation gate.
- **vLLM nightly/source dependency.** The NVFP4 Spark recipe requires a vLLM
  nightly/source build; pin a known-good revision in provisioning to avoid drift.
- **OCR/LLM co-residence contention.** Both models share one GB10 GPU per Spark and their
  workloads overlap (see Serving topology). Measure overlap throughput; fall back to the
  role-split topology (spark-1 LLM / spark-2 OCR) if contention is material.
- **Structured-output repair behavior** may differ from OpenRouter/Anthropic (different
  schema strictness). Covered by the `metadata` validation gate.
- **Chandra serving API surface** — confirm during OCR implementation.
- **Spark prefill throughput for OCR** — large image prefill is compute-heavy; measure
  pages/sec on a Spark and decide whether OCR concurrency needs tuning.

## Non-goals

- No changes to the job/worker architecture, DefraDB schema, or agent logic.
- No TTS migration this round.
- No removal of cloud providers — they remain available for A/B and fallback.
