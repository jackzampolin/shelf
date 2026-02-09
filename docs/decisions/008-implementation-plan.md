# ADR 008 Implementation Plan

## Overview

This plan implements config and prompts in DefraDB per ADR 008. Three phases, each independently shippable.

**Key decisions from discussion:**
- API keys: Keep `${ENV_VAR}` syntax, resolve at runtime
- DefraDB bootstrap: Dynamic container naming (`shelf-defra-{hash}`) eliminates bootstrap config needs
- Migration: Clean slate - no migration path from existing config.yaml
- Templates: Go `text/template` syntax with auto-extracted variable lists

---

## Phase 1: Config in Database

### 1.1 DefraDB Container Naming ✅
**Goal**: Support multiple shelf instances on same machine

**Files modified:**
- `internal/defra/docker.go`

**Tasks:**
- [x] Generate deterministic container name from home directory hash
- [x] Format: `shelf-defra-{first8chars-of-sha256(homedir)}`
- [x] Added `GenerateContainerName(homePath)` function
- [x] Added `HomePath` field to `DockerConfig`
- [x] Updated `NewDockerManager()` to use dynamic name when `HomePath` is set
- [x] Updated `cmd/shelf/serve.go` to pass `HomePath`

### 1.2 Config Schema ✅
**Goal**: Define Config collection in DefraDB

**Files created:**
- `internal/schema/schemas/config.graphql`

**Schema:**
```graphql
type Config {
  key: String! @index(unique: true)
  value: JSON!
  description: String
}
```

**Tasks:**
- [x] Create `config.graphql` schema file
- [x] Add Config to `internal/schema/registry.go` (Order: 0, before Job)
- [x] Test schema initialization

### 1.3 Config Store ✅
**Goal**: Read/write config from DefraDB instead of YAML

**Files created:**
- `internal/config/store.go`
- `internal/config/store_test.go`

**Interface:**
```go
type Store interface {
    Get(ctx context.Context, key string) (*Entry, error)
    Set(ctx context.Context, key string, value any, description string) error
    GetAll(ctx context.Context) (map[string]Entry, error)
    GetByPrefix(ctx context.Context, prefix string) (map[string]Entry, error)
    Delete(ctx context.Context, key string) error
}

type Entry struct {
    Key         string
    Value       any
    Description string
    DocID       string
}
```

**Tasks:**
- [x] Implement DefraDB-backed Store (no caching - read fresh each time)
- [x] Keep `ResolveEnvVars()` for `${ENV_VAR}` expansion
- [x] Implement `StoreToProviderRegistryConfig()` that reads from Store

### 1.4 Config Seeding ✅
**Goal**: Seed defaults on first run

**Files created:**
- `internal/config/defaults.go`
- `internal/config/defaults_test.go`

**Default config keys:** (17 total)
```
providers.ocr.mistral.type = "mistral-ocr"
providers.ocr.mistral.api_key = "${MISTRAL_API_KEY}"
providers.ocr.mistral.rate_limit = 6.0
providers.ocr.mistral.enabled = true

providers.ocr.paddle.type = "deepinfra"
providers.ocr.paddle.model = "PaddlePaddle/PaddleOCR-VL-0.9B"
providers.ocr.paddle.api_key = "${DEEPINFRA_API_KEY}"
providers.ocr.paddle.rate_limit = 10.0
providers.ocr.paddle.enabled = true

providers.llm.openrouter.type = "openrouter"
providers.llm.openrouter.model = "anthropic/claude-opus-4.6"
providers.llm.openrouter.api_key = "${OPENROUTER_API_KEY}"
providers.llm.openrouter.rate_limit = 150.0
providers.llm.openrouter.enabled = true

defaults.ocr_providers = ["mistral", "paddle"]
defaults.llm_provider = "openrouter"
defaults.max_workers = 10
```

**Tasks:**
- [x] Extract defaults to `defaults.go` as `[]Entry` via `DefaultEntries()`
- [x] Add `SeedDefaults(ctx, store, logger)` function
- [x] Add `GetDefault(key)` and `ResetToDefault(ctx, store, key)` helpers
- [x] Handle idempotency (skip if keys exist)

### 1.5 Integrate Store into Server ✅
**Goal**: Replace file-based config.Manager with DB-backed Store

**Files modified:**
- `internal/svcctx/svcctx.go`
- `internal/server/server.go`

**Tasks:**
- [x] Add `ConfigStore` to svcctx.Services
- [x] Add `svcctx.ConfigStoreFrom(ctx)` extractor
- [x] Update server startup to create ConfigStore after schema init
- [x] Call `SeedDefaults()` in server startup
- [ ] Update providers.Registry initialization to use Store (deferred - existing file config still works)
- [ ] Remove/deprecate file-based config.Manager (deferred to later)

### 1.6 Settings API Endpoints ✅
**Goal**: CRUD for config via HTTP

**Files created:**
- `internal/server/endpoints/settings.go`

**Endpoints:**
```
GET  /api/settings           - List all config entries
GET  /api/settings/{key...}  - Get single entry (key is URL path)
PUT  /api/settings/{key...}  - Update entry
POST /api/settings/reset/{key...} - Reset to default
```

**Tasks:**
- [x] Implement ListSettingsEndpoint
- [x] Implement GetSettingEndpoint
- [x] Implement UpdateSettingEndpoint
- [x] Implement ResetSettingEndpoint
- [x] Add to endpoint registry
- [x] Add CLI commands via Command() method

### 1.7 Settings Web UI ✅
**Goal**: `/settings` page for viewing/editing config

**Files created:**
- `web/src/routes/settings.tsx`

**Files modified:**
- `web/src/routes/__root.tsx` (added Settings nav link)

**UI Features:**
- [x] Grouped display by prefix (providers.ocr, providers.llm, defaults)
- [x] Inline editing with save/cancel
- [x] Visual indicator for env var references (`${...}`) with purple badge
- [x] Reset to default button per entry
- [x] Edit button per entry
- [x] Refresh button

**Tasks:**
- [x] Create settings route
- [x] Implement grouped config display
- [x] Implement inline editing
- [x] Add to navigation

### 1.8 Cleanup (Partially Complete)
**Tasks:**
- [ ] Remove `~/.shelf/config.yaml` file support (deferred - file config still used for bootstrap)
- [ ] Update `shelf init` or remove if no longer needed (deferred)
- [x] Update documentation (this file)

**Notes:**
The existing file-based config.Manager is still used for:
1. DefraDB container configuration (container_name, image, port)
2. Initial provider configuration before DB is available

Full migration to DB-only config requires updating serve.go to read provider
config from DB after seeding is complete. This is deferred to avoid complexity
in the initial implementation.

---

## Phase 2: Prompt Linking (Traceability) ✅

### 2.1 LLMCall Schema ✅
**Goal**: Track every LLM call with prompt reference

**Files created:**
- `internal/schema/schemas/llmcall.graphql`

**Schema:**
```graphql
type LLMCall {
  id: String! @index(unique: true)
  timestamp: DateTime!
  latency_ms: Int!
  book_id: String @index
  page_id: String @index
  job_id: String @index
  prompt_key: String! @index
  prompt_cid: String
  provider: String!
  model: String!
  temperature: Float
  input_tokens: Int!
  output_tokens: Int!
  response: String!
  tool_calls: JSON
  success: Boolean!
  error: String
}
```

**Tasks:**
- [x] Create schema file
- [x] Add to registry (Order: 9)
- [x] Test initialization

### 2.2 LLM Call Recording ✅
**Goal**: Record every LLM/agent call to DefraDB

**Files created:**
- `internal/llmcall/call.go` - Call struct and FromChatResult converter
- `internal/llmcall/store.go` - Store for querying calls
- `internal/llmcall/recorder.go` - Fire-and-forget recorder via Sink

**Files modified:**
- `internal/jobs/job.go` - Added PageID, PromptKey to WorkUnitMetrics
- `internal/jobs/provider_pool.go` - Hook into recordMetrics to also record LLMCalls
- `internal/svcctx/svcctx.go` - Added LLMCallStore to Services
- `internal/server/server.go` - Initialize LLMCallStore

**Tasks:**
- [x] Create llmcall package with Call, Store, Recorder
- [x] Hook into provider_pool's recordMetrics()
- [x] Pass promptKey through WorkUnitMetrics
- [x] For Phase 2, promptCID is empty (filled in Phase 3)

### 2.3 Call History Endpoints ✅
**Goal**: Query LLM call history

**Files created:**
- `internal/server/endpoints/llmcalls.go`

**Endpoints:**
```
GET /api/llmcalls                    - List calls (with filters)
GET /api/llmcalls/{id}               - Get single call
GET /api/llmcalls/counts/{book_id}   - Calls count by prompt key for a book
```

**Tasks:**
- [x] Implement list endpoint with filters (book, page, job, promptKey, provider, model, success)
- [x] Implement detail endpoint
- [x] Implement counts by prompt key endpoint
- [x] Add CLI: `shelf api llmcalls list`, `get`, `counts`

### 2.4 Call History UI ✅
**Goal**: View LLM calls in web UI

**Files created:**
- `web/src/routes/llmcalls.tsx` - Dedicated LLM calls page

**Files modified:**
- `web/src/routes/__root.tsx` - Added LLM Calls nav link

**Tasks:**
- [x] Create /llmcalls page with filterable table
- [x] Show: timestamp, model, tokens, latency, promptKey
- [x] Detail modal with full response and tool calls
- [x] Link to book and job from call details
- [ ] Add LLM calls tab to book detail page (deferred)
- [ ] Add LLM calls tab to page viewer (deferred)

---

## Phase 3: Prompts in Database

### 3.1 Prompt Schema
**Goal**: Store prompts in DefraDB

**Files to create:**
- `internal/schema/schemas/prompt.graphql`

**Schema:**
```graphql
type Prompt {
  key: String! @index(unique: true)
  text: String!
  description: String
  variables: [String!]
}

type BookPromptOverride {
  book: Book!
  promptKey: String!
  promptCID: String
  customText: String
}
```

**Tasks:**
- [ ] Create schema files
- [ ] Add to registry
- [ ] Test initialization

### 3.2 Prompt Store
**Goal**: Load prompts from DefraDB with book-level resolution

**Files to create:**
- `internal/prompts/store.go`
- `internal/prompts/store_test.go`

**Interface:**
```go
type PromptStore interface {
    // Get returns the resolved prompt for a key, with optional book override
    Get(ctx context.Context, key string, bookID string) (*ResolvedPrompt, error)

    // GetGlobal returns the global prompt (no book resolution)
    GetGlobal(ctx context.Context, key string) (*Prompt, error)

    // Update updates a global prompt
    Update(ctx context.Context, key, text string) error

    // SetBookOverride sets a book-specific prompt override
    SetBookOverride(ctx context.Context, bookID, promptKey, customText string) error

    // ClearBookOverride removes a book-specific override
    ClearBookOverride(ctx context.Context, bookID, promptKey string) error
}

type ResolvedPrompt struct {
    Key       string
    Text      string
    CID       string   // Version CID for traceability
    Variables []string
    IsOverride bool    // true if book-level override
}
```

**Tasks:**
- [ ] Implement PromptStore (no caching - read fresh each time)
- [ ] Resolution order: BookPromptOverride > Global Prompt

### 3.3 Template Variable Extraction
**Goal**: Auto-extract variables from Go templates

**Files to create:**
- `internal/prompts/template.go`
- `internal/prompts/template_test.go`

**Tasks:**
- [ ] Parse Go template and extract action nodes
- [ ] Extract variable names (e.g., `{{.ScanID}}` -> "ScanID")
- [ ] Use for both seeding and validation

### 3.4 Prompt Seeding
**Goal**: Seed default prompts from code

**Files to create:**
- `internal/prompts/defaults.go`

**Default prompt keys:**
```
agents.toc_finder.system
agents.toc_finder.user
stages.blend.system
stages.extract_toc.system
stages.label.system
stages.metadata.system
```

**Tasks:**
- [ ] Extract all prompts from current Go constants
- [ ] Structure as map[string]PromptDefault with text + description
- [ ] Auto-extract variables via template parsing
- [ ] Add `SeedPrompts(ctx, store)` function
- [ ] Call in server startup

### 3.5 Integrate Prompts into Agents/Stages
**Goal**: Load prompts from DB instead of constants

**Files to modify:**
- `internal/agents/toc_finder/prompt.go`
- `internal/prompts/blend/prompt.go`
- `internal/prompts/extract_toc/prompt.go`
- `internal/prompts/label/prompt.go`
- `internal/prompts/metadata/prompt.go`
- (and their workunit.go files)

**Tasks:**
- [ ] Add PromptStore to svcctx
- [ ] Modify agent/stage creation to load prompts from store
- [ ] Pass book ID for override resolution
- [ ] Thread promptCID through to LLMCall recording (from Phase 2)

### 3.6 Prompt API Endpoints
**Goal**: CRUD for prompts

**Files to create:**
- `internal/server/endpoints/prompts.go`

**Endpoints:**
```
GET  /api/prompts                     - List all prompts
GET  /api/prompts/:key                - Get prompt with version history
PUT  /api/prompts/:key                - Update prompt
GET  /api/prompts/:key/history        - Get version history (via _commits)

GET  /api/books/:bookId/prompts       - List prompts with book overrides resolved
PUT  /api/books/:bookId/prompts/:key  - Set book override
DELETE /api/books/:bookId/prompts/:key - Clear book override
```

**Tasks:**
- [ ] Implement global prompt CRUD
- [ ] Implement book override CRUD
- [ ] Add history endpoint using DefraDB _commits
- [ ] Add CLI commands

### 3.7 Prompt Web UI
**Goal**: Edit prompts in web UI

**Files to create:**
- `web/src/routes/settings.prompts.tsx` (or extend settings)
- `web/src/routes/books.$bookId.settings.tsx`

**Global Prompts UI (`/settings/prompts`):**
- List all prompts grouped by category
- Edit prompt text (full-screen editor for long prompts)
- Show variables used
- Version history view

**Book Settings UI (`/books/:id/settings`):**
- Show resolved prompts for this book
- Visual indicator: "inherited" vs "overridden"
- Edit to create override
- Reset button to clear override

**Tasks:**
- [ ] Create prompts settings page
- [ ] Implement prompt editor component
- [ ] Create book settings page
- [ ] Implement override editing
- [ ] Add version history viewer

### 3.8 CID Recording
**Goal**: Complete traceability - every LLM call records exact prompt version

**Files to modify:**
- `internal/providers/` (LLM recording)
- `internal/agent/agent.go`

**Tasks:**
- [ ] When loading prompt, capture CID
- [ ] Pass CID through to LLM call recording
- [ ] Update LLMCall documents with promptCID

---

## Implementation Order

Recommended sequence within each phase:

**Phase 1** (estimate: foundation work)
1. 1.1 Container naming (quick win, unblocks multi-instance)
2. 1.2 Config schema
3. 1.3 Config store
4. 1.4 Config seeding
5. 1.5 Server integration
6. 1.6 API endpoints
7. 1.7 Web UI
8. 1.8 Cleanup

**Phase 2** (estimate: builds on Phase 1)
1. 2.1 LLMCall schema
2. 2.2 Recording integration
3. 2.3 API endpoints
4. 2.4 Web UI

**Phase 3** (estimate: largest phase)
1. 3.1 Prompt schema
2. 3.2 Prompt store
3. 3.3 Template extraction
4. 3.4 Prompt seeding
5. 3.5 Agent/stage integration
6. 3.6 API endpoints
7. 3.7 Web UI
8. 3.8 CID recording

---

## Testing Strategy

Each component should have:
1. Unit tests with mock DefraDB client
2. Integration tests against real DefraDB (tagged `//go:build integration`)

Key test scenarios:
- Config: CRUD, env var resolution, key validation
- Prompts: Resolution order, template rendering, CID capture
- LLMCalls: Recording, queries, book/page filtering

---

## Resolved Questions

1. **No caching**: Read config/prompts fresh from DefraDB each time. Optimize later if needed.

2. **Concurrent edits**: DefraDB uses Merkle CRDTs with deterministic merge - concurrent edits automatically converge to the same state. Last-write-wins is natural.

3. **Prompt validation**: Yes - validate Go template syntax on save using `text/template.Parse()`. Also auto-extract variables via AST walk of the parsed template.

## Sources

- [DefraDB Merkle CRDTs](https://open.source.network/blog/how-defradb-uses-merkle-crdts-to-maintain-data-consistency-and-conflict-free) - Conflict resolution strategy
