# Local Inference Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the shared provider-layer scaffolding that the local LLM (Qwen3.6-35B-A3B-NVFP4) and OCR (Chandra) sub-specs depend on: configurable per-provider base URLs, round-robin endpoint selection, keyless registration for local servers, fail-fast startup health checks, provider-routing validation, and zero-cost metrics semantics.

**Architecture:** Purely additive changes to `internal/config` and `internal/providers`, plus startup wiring in `internal/server`. No new provider *types* are added here (that is the LLM/OCR sub-specs); this plan makes the existing OpenRouter/Mistral plumbing honor a configurable base URL and adds the cross-cutting infra both local providers will reuse. Existing cloud providers keep working unchanged.

**Tech Stack:** Go, standard `testing` package (subtests via `t.Run`, no testify), `net/http/httptest` for HTTP seams, DefraDB-backed config store.

## Global Constraints

- Go standard `testing` only — subtests via `t.Run`, table tests optional, **no testify**.
- DefraDB schemas use **no NonNull (`!`) fields** (not touched here, but a project rule).
- Backward compatibility: existing cloud providers (OpenRouter `openrouter`, Mistral `mistral-ocr`) must continue to register and run unchanged when no `base_urls` are configured.
- Commit message trailer (every commit):
  ```
  🤖 Generated with [Claude Code](https://claude.com/claude-code)

  Co-Authored-By: Claude <noreply@anthropic.com>
  ```
- Do not commit to `main` directly — this plan executes on a `local-inference` branch.
- Run `make build:backend` (or `go build ./...`) after signature-changing tasks to catch ripple.

---

### Task 1: Add `base_urls` to provider config (schema + registry config + env resolution)

**Files:**
- Modify: `internal/config/schema.go` (`OCRProviderCfg`, `LLMProviderCfg`)
- Modify: `internal/providers/registry.go` (`OCRProviderConfig`, `LLMProviderConfig` structs, ~lines 257-290)
- Modify: `internal/config/config.go` (`ToProviderRegistryConfig`, ~lines 135-180; add `resolveEnvVarsSlice` helper near `ResolveEnvVars` ~line 121)
- Test: `internal/config/config_test.go`

**Interfaces:**
- Produces: `LLMProviderCfg.BaseURLs []string`, `OCRProviderCfg.BaseURLs []string` (config layer); `providers.LLMProviderConfig.BaseURLs []string`, `providers.OCRProviderConfig.BaseURLs []string` (registry layer). `ToProviderRegistryConfig` copies them through `resolveEnvVarsSlice`. Tasks 3 and 4 consume `providers.*ProviderConfig.BaseURLs`.

- [ ] **Step 1: Write the failing test**

In `internal/config/config_test.go`:

```go
func TestToProviderRegistryConfig_ResolvesBaseURLs(t *testing.T) {
	os.Setenv("SPARK1", "http://100.74.68.88:8000/v1")
	defer os.Unsetenv("SPARK1")

	c := &Config{
		LLMProviders: map[string]LLMProviderCfg{
			"local-llm": {
				Type:     "openai-compat",
				Model:    "nvidia/Qwen3.6-35B-A3B-NVFP4",
				BaseURLs: []string{"${SPARK1}", "http://100.86.62.91:8000/v1"},
				Enabled:  true,
			},
		},
		OCRProviders: map[string]OCRProviderCfg{
			"local-ocr": {Type: "chandra", BaseURLs: []string{"${SPARK1}"}, Enabled: true},
		},
	}

	rc := c.ToProviderRegistryConfig()

	llm := rc.LLMProviders["local-llm"].BaseURLs
	if len(llm) != 2 || llm[0] != "http://100.74.68.88:8000/v1" || llm[1] != "http://100.86.62.91:8000/v1" {
		t.Fatalf("LLM BaseURLs = %v, want resolved spark URLs", llm)
	}
	ocr := rc.OCRProviders["local-ocr"].BaseURLs
	if len(ocr) != 1 || ocr[0] != "http://100.74.68.88:8000/v1" {
		t.Fatalf("OCR BaseURLs = %v, want resolved spark URL", ocr)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/config/ -run TestToProviderRegistryConfig_ResolvesBaseURLs -v`
Expected: FAIL — `BaseURLs` is not a field of `LLMProviderCfg` / `OCRProviderCfg` (compile error).

- [ ] **Step 3: Add the config-layer fields**

In `internal/config/schema.go`, add to `LLMProviderCfg` (after `Enabled`):

```go
	Enabled   bool     `mapstructure:"enabled" yaml:"enabled"`
	BaseURLs  []string `mapstructure:"base_urls" yaml:"base_urls"` // Optional self-hosted endpoints (round-robined). Supports ${ENV_VAR}.
```

And to `OCRProviderCfg` (after `IncludeImages`):

```go
	IncludeImages bool     `mapstructure:"include_images" yaml:"include_images"` // Extract images (Mistral only)
	BaseURLs      []string `mapstructure:"base_urls" yaml:"base_urls"`          // Optional self-hosted endpoints (round-robined). Supports ${ENV_VAR}.
```

- [ ] **Step 4: Add the registry-layer fields**

In `internal/providers/registry.go`, add `BaseURLs []string` to both structs:

```go
type OCRProviderConfig struct {
	Type          string
	APIKey        string
	RateLimit     float64
	Enabled       bool
	IncludeImages bool
	BaseURLs      []string // Optional self-hosted endpoints (round-robined)
}

type LLMProviderConfig struct {
	Type      string
	Model     string
	APIKey    string
	RateLimit float64
	Enabled   bool
	BaseURLs  []string // Optional self-hosted endpoints (round-robined)
}
```

- [ ] **Step 5: Add the env-resolving conversion**

In `internal/config/config.go`, add a helper next to `ResolveEnvVars`:

```go
// resolveEnvVarsSlice applies ResolveEnvVars to each element, returning nil for an empty input.
func resolveEnvVarsSlice(values []string) []string {
	if len(values) == 0 {
		return nil
	}
	out := make([]string, len(values))
	for i, v := range values {
		out[i] = ResolveEnvVars(v)
	}
	return out
}
```

In `ToProviderRegistryConfig`, add `BaseURLs` to both conversions:

```go
	for name, ocr := range c.OCRProviders {
		cfg.OCRProviders[name] = providers.OCRProviderConfig{
			Type:          ocr.Type,
			APIKey:        ResolveEnvVars(ocr.APIKey),
			RateLimit:     ocr.RateLimit,
			Enabled:       ocr.Enabled,
			IncludeImages: ocr.IncludeImages,
			BaseURLs:      resolveEnvVarsSlice(ocr.BaseURLs),
		}
	}

	for name, llm := range c.LLMProviders {
		cfg.LLMProviders[name] = providers.LLMProviderConfig{
			Type:      llm.Type,
			Model:     llm.Model,
			APIKey:    ResolveEnvVars(llm.APIKey),
			RateLimit: llm.RateLimit,
			Enabled:   llm.Enabled,
			BaseURLs:  resolveEnvVarsSlice(llm.BaseURLs),
		}
	}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `go test ./internal/config/ -run TestToProviderRegistryConfig_ResolvesBaseURLs -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add internal/config/schema.go internal/providers/registry.go internal/config/config.go internal/config/config_test.go
git commit -m "feat: add base_urls to provider config with env resolution"
```

---

### Task 2: Round-robin endpoint pool

**Files:**
- Create: `internal/providers/endpoints.go`
- Test: `internal/providers/endpoints_test.go`

**Interfaces:**
- Produces: `providers.EndpointPool` with `NewEndpointPool(urls []string) *EndpointPool`, `(*EndpointPool).Next() string`, `(*EndpointPool).Len() int`. The LLM/OCR sub-specs construct one from `LLMProviderConfig.BaseURLs` and call `Next()` per request.

- [ ] **Step 1: Write the failing test**

Create `internal/providers/endpoints_test.go`:

```go
package providers

import (
	"sync"
	"testing"
)

func TestEndpointPool_RoundRobin(t *testing.T) {
	p := NewEndpointPool([]string{"a", "b", "c"})
	got := []string{p.Next(), p.Next(), p.Next(), p.Next()}
	want := []string{"a", "b", "c", "a"}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("Next() sequence = %v, want %v", got, want)
		}
	}
}

func TestEndpointPool_Single(t *testing.T) {
	p := NewEndpointPool([]string{"only"})
	if p.Next() != "only" || p.Next() != "only" {
		t.Fatalf("single-endpoint pool must always return 'only'")
	}
}

func TestEndpointPool_Empty(t *testing.T) {
	p := NewEndpointPool(nil)
	if p.Len() != 0 {
		t.Fatalf("Len() = %d, want 0", p.Len())
	}
	if p.Next() != "" {
		t.Fatalf("Next() on empty pool = %q, want \"\"", p.Next())
	}
}

func TestEndpointPool_ConcurrentSafe(t *testing.T) {
	p := NewEndpointPool([]string{"a", "b"})
	var wg sync.WaitGroup
	for i := 0; i < 100; i++ {
		wg.Add(1)
		go func() { defer wg.Done(); _ = p.Next() }()
	}
	wg.Wait() // race detector (go test -race) asserts no data race
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/providers/ -run TestEndpointPool -v`
Expected: FAIL — `NewEndpointPool` undefined (compile error).

- [ ] **Step 3: Implement the endpoint pool**

Create `internal/providers/endpoints.go`:

```go
package providers

import "sync/atomic"

// EndpointPool round-robins across a fixed set of base URLs.
// It is safe for concurrent use.
type EndpointPool struct {
	urls    []string
	counter atomic.Uint64
}

// NewEndpointPool creates a pool over a copy of the given base URLs.
// An empty/nil slice yields a pool whose Next returns "".
func NewEndpointPool(urls []string) *EndpointPool {
	cp := make([]string, len(urls))
	copy(cp, urls)
	return &EndpointPool{urls: cp}
}

// Len returns the number of endpoints.
func (p *EndpointPool) Len() int { return len(p.urls) }

// Next returns the next base URL in round-robin order, or "" if the pool is empty.
func (p *EndpointPool) Next() string {
	n := uint64(len(p.urls))
	if n == 0 {
		return ""
	}
	i := p.counter.Add(1) - 1
	return p.urls[i%n]
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/providers/ -run TestEndpointPool -race -v`
Expected: PASS (and no race).

- [ ] **Step 5: Commit**

```bash
git add internal/providers/endpoints.go internal/providers/endpoints_test.go
git commit -m "feat: add round-robin EndpointPool for multi-host providers"
```

---

### Task 3: Allow keyless registration when `base_urls` is set

**Files:**
- Modify: `internal/providers/registry.go` — `Reload` (LLM guard ~line 322, OCR guard ~line 345) and `applyConfig` (LLM guard ~line 423, OCR guard ~line 434)
- Test: `internal/providers/registry_test.go`

**Interfaces:**
- Consumes: `LLMProviderConfig.BaseURLs` (Task 1).
- Produces: a local provider config with empty `APIKey` but non-empty `BaseURLs` now registers. TTS guards are intentionally left unchanged (TTS is out of scope this round).

- [ ] **Step 1: Write the failing test**

In `internal/providers/registry_test.go`:

```go
func TestReload_RegistersKeylessLocalProvider(t *testing.T) {
	r := NewRegistry()
	r.Reload(RegistryConfig{
		LLMProviders: map[string]LLMProviderConfig{
			"local-llm":      {Type: "openrouter", Model: "x", APIKey: "", BaseURLs: []string{"http://spark-1:8000/v1"}, Enabled: true},
			"keyless-no-url": {Type: "openrouter", Model: "x", APIKey: "", Enabled: true},
		},
	})

	if !r.HasLLM("local-llm") {
		t.Error("expected keyless provider WITH base_urls to register")
	}
	if r.HasLLM("keyless-no-url") {
		t.Error("expected keyless provider WITHOUT base_urls to be skipped")
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/providers/ -run TestReload_RegistersKeylessLocalProvider -v`
Expected: FAIL — `local-llm` is skipped by the `APIKey == ""` guard, so `HasLLM("local-llm")` is false.

- [ ] **Step 3: Relax the LLM and OCR guards**

In `internal/providers/registry.go`, change the guard in all **four** locations — the LLM and OCR loops inside both `Reload` and `applyConfig`. Replace:

```go
		if !provCfg.Enabled || provCfg.APIKey == "" {
			continue
		}
```

with:

```go
		if !provCfg.Enabled || (provCfg.APIKey == "" && len(provCfg.BaseURLs) == 0) {
			continue
		}
```

Leave the **TTS** loops' guards (`Reload` ~line 371, `applyConfig` ~line 448) unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/providers/ -run TestReload_RegistersKeylessLocalProvider -v`
Expected: PASS

- [ ] **Step 5: Run the full providers package to confirm no regressions**

Run: `go test ./internal/providers/ -v`
Expected: PASS (existing cloud-provider registration tests still green).

- [ ] **Step 6: Commit**

```bash
git add internal/providers/registry.go internal/providers/registry_test.go
git commit -m "feat: allow keyless provider registration when base_urls is set"
```

---

### Task 4: Thread `base_urls` into the OpenRouter LLM factory

**Files:**
- Modify: `internal/providers/registry.go` — `createLLMClient` (~lines 458-470)
- Test: `internal/providers/registry_test.go`

**Interfaces:**
- Consumes: `LLMProviderConfig.BaseURLs` (Task 1).
- Produces: when `BaseURLs` is non-empty, the OpenRouter client points at `BaseURLs[0]` instead of `https://openrouter.ai/api/v1`. (Full round-robin across multiple URLs is implemented by the new `openai-compat` client in the LLM sub-spec; here we wire the first URL so the plumbing is testable end-to-end and so `openrouter`-type configs can target a local OpenAI-compatible server.) OCR base-URL threading is deferred to the OCR sub-spec (Chandra provider).

- [ ] **Step 1: Write the failing test**

In `internal/providers/registry_test.go`:

```go
func TestCreateLLMClient_UsesBaseURL(t *testing.T) {
	hit := make(chan string, 1)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		select {
		case hit <- r.URL.Path:
		default:
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer srv.Close()

	client := createLLMClient(LLMProviderConfig{
		Type:     "openrouter",
		Model:    "x",
		APIKey:   "test-key",
		BaseURLs: []string{srv.URL},
	})
	if client == nil {
		t.Fatal("expected non-nil client")
	}
	if err := client.HealthCheck(context.Background()); err != nil {
		t.Fatalf("HealthCheck() error = %v", err)
	}

	select {
	case path := <-hit:
		if path != "/auth/key" {
			t.Fatalf("health check hit %q, want /auth/key", path)
		}
	default:
		t.Fatal("health check did not reach the configured base URL")
	}
}
```

Ensure these imports exist in `registry_test.go`: `context`, `net/http`, `net/http/httptest`, `testing`.

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/providers/ -run TestCreateLLMClient_UsesBaseURL -v`
Expected: FAIL — without threading, `HealthCheck` calls `https://openrouter.ai/api/v1/auth/key`, so the test server is never hit (and/or the live call errors).

- [ ] **Step 3: Thread BaseURLs[0] into the factory**

In `internal/providers/registry.go`, update `createLLMClient`:

```go
func createLLMClient(cfg LLMProviderConfig) LLMClient {
	switch cfg.Type {
	case "openrouter":
		orc := OpenRouterConfig{
			APIKey:       cfg.APIKey,
			DefaultModel: cfg.Model,
			RPS:          cfg.RateLimit, // Pass RPS from config
		}
		if len(cfg.BaseURLs) > 0 {
			orc.BaseURL = cfg.BaseURLs[0]
		}
		return NewOpenRouterClient(orc)
	default:
		return nil
	}
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/providers/ -run TestCreateLLMClient_UsesBaseURL -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add internal/providers/registry.go internal/providers/registry_test.go
git commit -m "feat: point openrouter LLM factory at configured base_urls"
```

---

### Task 5: Fail-fast startup health checks

**Files:**
- Modify: `internal/jobs/scheduler_workers.go` — `InitFromRegistry` (~line 48), `InitFromRegistryWithHealthCheck` (~line 55; add `failFast` param + early returns for LLM/OCR/TTS loops), add `InitFromRegistryStrict`
- Modify: `internal/config/schema.go` — `DefaultsCfg` (add `RequireHealthyProviders`), `DefaultConfig` (set it true)
- Modify: `internal/server/server.go` — replace the `InitFromRegistry` call (~line 295)
- Test: `internal/jobs/scheduler_test.go`

**Interfaces:**
- Consumes: `providers.LLMClient.HealthCheck` (existing).
- Produces: `(*Scheduler).InitFromRegistryWithHealthCheck(ctx, registry, runHealthChecks, failFast bool) error` (signature gains `failFast`); `(*Scheduler).InitFromRegistryStrict(ctx, registry) error`; `config.DefaultsCfg.RequireHealthyProviders bool`. The only existing caller of the health-check variant is the `InitFromRegistry` wrapper, so no other call sites change.

- [ ] **Step 1: Write the failing test**

In `internal/jobs/scheduler_test.go`:

```go
func TestInitFromRegistry_FailFastOnUnhealthy(t *testing.T) {
	reg := providers.NewRegistry()
	bad := providers.NewMockClient()
	bad.ShouldFail = true // makes HealthCheck return an error
	reg.RegisterLLM("bad", bad)

	s1 := NewScheduler(SchedulerConfig{Logger: slog.Default()})
	if err := s1.InitFromRegistryWithHealthCheck(context.Background(), reg, true, true); err == nil {
		t.Fatal("expected error when health check fails and failFast=true")
	}

	s2 := NewScheduler(SchedulerConfig{Logger: slog.Default()})
	if err := s2.InitFromRegistryWithHealthCheck(context.Background(), reg, true, false); err != nil {
		t.Fatalf("expected no error with failFast=false (warn only), got %v", err)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/jobs/ -run TestInitFromRegistry_FailFastOnUnhealthy -v`
Expected: FAIL — `InitFromRegistryWithHealthCheck` currently takes 3 args, not 4 (compile error).

- [ ] **Step 3: Add `failFast` to the scheduler init**

In `internal/jobs/scheduler_workers.go`, update the wrapper and the health-check function. Replace the `InitFromRegistry` body:

```go
func (s *Scheduler) InitFromRegistry(registry *providers.Registry) error {
	return s.InitFromRegistryWithHealthCheck(context.Background(), registry, false, false)
}

// InitFromRegistryStrict runs health checks and fails fast on the first unreachable provider.
func (s *Scheduler) InitFromRegistryStrict(ctx context.Context, registry *providers.Registry) error {
	return s.InitFromRegistryWithHealthCheck(ctx, registry, true, true)
}
```

Change the signature to add `failFast bool`:

```go
func (s *Scheduler) InitFromRegistryWithHealthCheck(ctx context.Context, registry *providers.Registry, runHealthChecks, failFast bool) error {
```

In each of the three provider loops (LLM, OCR, TTS), replace the existing warn-only health block. For the **LLM** loop:

```go
		if runHealthChecks {
			if err := client.HealthCheck(ctx); err != nil {
				if failFast {
					return fmt.Errorf("LLM provider %q failed health check: %w", name, err)
				}
				s.logger.Warn("LLM provider health check failed", "name", name, "error", err)
			} else {
				s.logger.Debug("LLM provider health check passed", "name", name)
			}
		}
```

For the **OCR** loop (same shape, `provider` is the loop var):

```go
		if runHealthChecks {
			if err := provider.HealthCheck(ctx); err != nil {
				if failFast {
					return fmt.Errorf("OCR provider %q failed health check: %w", name, err)
				}
				s.logger.Warn("OCR provider health check failed", "name", name, "error", err)
			} else {
				s.logger.Debug("OCR provider health check passed", "name", name)
			}
		}
```

For the **TTS** loop:

```go
		if runHealthChecks {
			if err := provider.HealthCheck(ctx); err != nil {
				if failFast {
					return fmt.Errorf("TTS provider %q failed health check: %w", name, err)
				}
				s.logger.Warn("TTS provider health check failed", "name", name, "error", err)
			} else {
				s.logger.Debug("TTS provider health check passed", "name", name)
			}
		}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/jobs/ -run TestInitFromRegistry_FailFastOnUnhealthy -v`
Expected: PASS

- [ ] **Step 5: Add the config flag**

In `internal/config/schema.go`, add a field to `DefaultsCfg` (after `MaxWorkers`):

```go
	MaxWorkers              int  `mapstructure:"max_workers" yaml:"max_workers"`
	RequireHealthyProviders bool `mapstructure:"require_healthy_providers" yaml:"require_healthy_providers"` // Fail startup if a configured provider's health check fails
```

In `DefaultConfig()`, set it in the `Defaults` literal (after `MaxWorkers: 10,`):

```go
		Defaults: DefaultsCfg{
			OCRProviders:            []string{"mistral"},
			LLMProvider:             "openrouter",
			TTSProvider:             "openai",
			OpenAITTSInstructions:   "",
			MaxWorkers:              10,
			RequireHealthyProviders: true,
		},
```

> Note: configs loaded from an existing YAML file that lacks `require_healthy_providers` get the Go zero value (`false` → warn-only), preserving today's behavior for current deployments. New configs written via `DefaultConfig`/`WriteDefault` get `true`. Local-inference deployments should set it explicitly.

- [ ] **Step 6: Wire it into server startup**

In `internal/server/server.go`, replace the existing block (~lines 294-298):

```go
	// Initialize workers from provider registry
	if err := s.scheduler.InitFromRegistry(s.registry); err != nil {
		_ = s.shutdown()
		return fmt.Errorf("failed to initialize workers: %w", err)
	}
```

with:

```go
	// Initialize workers from provider registry. For local inference a down
	// endpoint stalls the whole pipeline (no cloud fallback), so optionally fail fast.
	requireHealthy := false
	if s.configMgr != nil {
		requireHealthy = s.configMgr.Get().Defaults.RequireHealthyProviders
	}
	if err := s.scheduler.InitFromRegistryWithHealthCheck(ctx, s.registry, true, requireHealthy); err != nil {
		_ = s.shutdown()
		return fmt.Errorf("failed to initialize workers: %w", err)
	}
```

- [ ] **Step 7: Build and run affected tests**

Run: `go build ./... && go test ./internal/jobs/ ./internal/config/ ./internal/server/ -v`
Expected: PASS (and the build confirms no other caller broke from the signature change).

- [ ] **Step 8: Commit**

```bash
git add internal/jobs/scheduler_workers.go internal/jobs/scheduler_test.go internal/config/schema.go internal/server/server.go
git commit -m "feat: fail-fast startup health checks for providers"
```

---

### Task 6: Validate provider routing at startup

**Files:**
- Create: `internal/server/validate_providers.go`
- Modify: `internal/server/server.go` — add validation call after worker init (~line 299)
- Test: `internal/server/validate_providers_test.go`

**Interfaces:**
- Consumes: `providers.Registry.HasLLM`/`HasOCR`; `jobcfg.NewBuilder(store).ProcessBookConfig(ctx)` returning `process_book.Config` with `OcrProviders []string`, `MetadataProvider string`, `TocProvider string`.
- Produces: `validateProviderRouting(registry *providers.Registry, llmNames, ocrNames []string) error` and `dedupeNonEmpty(values ...string) []string`. Startup fails if a routed provider name is not registered.

**Rationale:** Registration comes from YAML (`ToProviderRegistryConfig`), but jobs select providers by name from the DefraDB settings store (`defaults.llm_provider` → `MetadataProvider`/`TocProvider`, `defaults.ocr_providers` → `OcrProviders`). These two sources can drift; this catches it at boot instead of at job-execution time.

- [ ] **Step 1: Write the failing test**

Create `internal/server/validate_providers_test.go`:

```go
package server

import (
	"testing"

	"github.com/jackzampolin/shelf/internal/providers"
)

func TestValidateProviderRouting(t *testing.T) {
	reg := providers.NewRegistry()
	reg.RegisterLLM("local-llm", providers.NewMockClient())
	reg.RegisterOCR("local-ocr", providers.NewMockOCRProvider())

	t.Run("all registered", func(t *testing.T) {
		if err := validateProviderRouting(reg, []string{"local-llm"}, []string{"local-ocr"}); err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
	})
	t.Run("missing llm", func(t *testing.T) {
		if err := validateProviderRouting(reg, []string{"nope"}, []string{"local-ocr"}); err == nil {
			t.Fatal("expected error for unregistered LLM provider")
		}
	})
	t.Run("missing ocr", func(t *testing.T) {
		if err := validateProviderRouting(reg, []string{"local-llm"}, []string{"nope"}); err == nil {
			t.Fatal("expected error for unregistered OCR provider")
		}
	})
	t.Run("empty names skipped", func(t *testing.T) {
		if err := validateProviderRouting(reg, []string{"local-llm", ""}, nil); err != nil {
			t.Fatalf("empty names should be ignored, got %v", err)
		}
	})
}

func TestDedupeNonEmpty(t *testing.T) {
	got := dedupeNonEmpty("a", "", "a", "b")
	if len(got) != 2 || got[0] != "a" || got[1] != "b" {
		t.Fatalf("dedupeNonEmpty = %v, want [a b]", got)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/server/ -run 'TestValidateProviderRouting|TestDedupeNonEmpty' -v`
Expected: FAIL — `validateProviderRouting` / `dedupeNonEmpty` undefined (compile error).

- [ ] **Step 3: Implement the validator**

Create `internal/server/validate_providers.go`:

```go
package server

import (
	"fmt"

	"github.com/jackzampolin/shelf/internal/providers"
)

// validateProviderRouting ensures every provider name the pipeline will route to
// is actually registered. Registration comes from YAML config while routing names
// come from the DefraDB settings store, so the two can drift; this surfaces a
// mismatch at startup instead of at job-execution time.
func validateProviderRouting(registry *providers.Registry, llmNames, ocrNames []string) error {
	for _, name := range llmNames {
		if name == "" {
			continue
		}
		if !registry.HasLLM(name) {
			return fmt.Errorf("configured LLM provider %q is not registered (check llm_providers and defaults.llm_provider)", name)
		}
	}
	for _, name := range ocrNames {
		if name == "" {
			continue
		}
		if !registry.HasOCR(name) {
			return fmt.Errorf("configured OCR provider %q is not registered (check ocr_providers and defaults.ocr_providers)", name)
		}
	}
	return nil
}

// dedupeNonEmpty returns the distinct non-empty values in input order.
func dedupeNonEmpty(values ...string) []string {
	seen := make(map[string]bool)
	var out []string
	for _, v := range values {
		if v == "" || seen[v] {
			continue
		}
		seen[v] = true
		out = append(out, v)
	}
	return out
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/server/ -run 'TestValidateProviderRouting|TestDedupeNonEmpty' -v`
Expected: PASS

- [ ] **Step 5: Wire the validation into startup**

In `internal/server/server.go`, immediately after the worker-init block from Task 5 (and before `s.scheduler.InitCPUPool(0)`), add:

```go
	// Validate that the providers jobs will route to are actually registered.
	pbCfg, err := jobcfg.NewBuilder(s.configStore).ProcessBookConfig(ctx)
	if err != nil {
		_ = s.shutdown()
		return fmt.Errorf("failed to load process-book config for provider validation: %w", err)
	}
	llmNames := dedupeNonEmpty(pbCfg.MetadataProvider, pbCfg.TocProvider)
	if err := validateProviderRouting(s.registry, llmNames, pbCfg.OcrProviders); err != nil {
		_ = s.shutdown()
		return fmt.Errorf("provider routing validation failed: %w", err)
	}
```

`jobcfg` is already imported in `server.go`. `s.configStore` is initialized earlier in startup (set from `config.NewStore`), so it is available here.

- [ ] **Step 6: Build and run server tests**

Run: `go build ./... && go test ./internal/server/ -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add internal/server/validate_providers.go internal/server/validate_providers_test.go internal/server/server.go
git commit -m "feat: validate provider routing names against registry at startup"
```

---

### Task 7: Document zero-cost metrics semantics (ADR)

**Files:**
- Create: `docs/decisions/009-local-inference-zero-cost.md`

**Interfaces:** None (documentation). No code change is required: local providers return `CostUSD: 0`, and `metrics.Metric.ToMap` already omits cost when `m.CostUSD > 0` is false (`internal/metrics/metric.go:87-89`), so zero-cost local calls simply carry no cost field while token/latency metrics remain populated.

- [ ] **Step 1: Verify the existing metrics guard (no change expected)**

Run: `grep -n "CostUSD > 0" internal/metrics/metric.go`
Expected: shows the guard `if m.CostUSD > 0 {` — confirming zero cost is already handled gracefully.

- [ ] **Step 2: Write the ADR**

Create `docs/decisions/009-local-inference-zero-cost.md`:

```markdown
# ADR 009: Zero Marginal Cost for Local Inference

## Status
Accepted

## Context
ADR 002 (Cost Tracking) treats per-call dollar cost as a first-class signal, sourced
from provider responses (OpenRouter returns `cost`/`native_total_cost`). With inference
moving to self-hosted models on local hardware (Qwen3.6-35B-A3B-NVFP4 and Chandra OCR on
the DGX Sparks), there is no per-call dollar cost — the marginal cost of a call is
effectively zero (amortized hardware + electricity).

## Decision
Local provider implementations report `CostUSD: 0` on their `ChatResult` / `OCRResult`.
The existing metrics path already accommodates this: `metrics.Metric.ToMap` only emits
`cost_usd` when it is greater than zero, so zero-cost local calls record no cost field
while still recording tokens, queue/execution latency, provider, and model.

For local inference the meaningful signals become **throughput (tokens/sec), latency, and
(future) GPU utilization** rather than dollars. Dashboards and summaries should not treat a
missing/zero `cost_usd` as an error for local providers.

## Consequences
- No schema or code change is required to support zero-cost calls.
- Cost-based dashboards will show $0 for local providers; this is expected, not a bug.
- If energy-cost estimation is desired later, it can be layered on as a separate, explicit
  estimate rather than overloading `cost_usd`.
- Cloud providers (OpenRouter/Mistral/OpenAI) remain registerable for A/B comparison and
  continue to report real dollar costs.
```

- [ ] **Step 3: Commit**

```bash
git add docs/decisions/009-local-inference-zero-cost.md
git commit -m "docs: ADR 009 zero marginal cost for local inference"
```

---

## Self-Review

**Spec coverage (Foundation section of the design doc):**
- `base_urls []string` config + per-element `ResolveEnvVars` → Task 1. ✓
- Round-robin across base_urls → Task 2 (helper) + Task 4 (first-URL threading; full round-robin consumed by the LLM sub-spec). ✓
- Optional auth (keyless local registration) → Task 3 (chose guard-relax over static-token; cleaner and testable). ✓
- Fail-fast health probes → Task 5. ✓
- Config-source coupling (YAML registration vs DB routing) assertion → Task 6. ✓
- Cost=0 semantics + ADR → Task 7. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every test shows assertions and run commands with expected output.

**Type consistency:** `BaseURLs []string` is the field name in all four structs (`LLMProviderCfg`, `OCRProviderCfg`, `providers.LLMProviderConfig`, `providers.OCRProviderConfig`). `InitFromRegistryWithHealthCheck(ctx, registry, runHealthChecks, failFast bool)` is used identically in the wrapper, the strict helper, the test, and the server call. `validateProviderRouting(registry, llmNames, ocrNames)` and `dedupeNonEmpty(...)` signatures match between definition, test, and server wiring. `process_book.Config` fields used (`OcrProviders`, `MetadataProvider`, `TocProvider`) match the verified struct.

**Out of scope (correctly deferred):** new `openai-compat` LLM client + multi-URL round-robin consumption (LLM sub-spec); `chandra` OCR provider + OCR base-URL threading (OCR sub-spec); all TTS work.
