# ADR 008: Config and Prompts in Database

## Status
Proposed

## Context
The current system stores configuration in `~/.shelf/config.yaml` and prompts are hardcoded in Go source files. This creates several limitations:

1. **No experimentation** - Changing prompts requires code changes and recompilation
2. **No per-book customization** - Every book uses the same prompts, even when edge cases need different handling
3. **No traceability** - When an LLM call produces bad output, we can't trace back to exactly which prompt produced it
4. **No iteration history** - Prompt improvements are lost in git history, not queryable

### User Story
> "I have a book with an older ToC format - lots of prose attached to each chapter entry. The default prompt misses this. I should be able to write a quick sentence explaining this and have it added to the prompt, or iterate on the full prompt entirely. And I should be able to see exactly which prompt version produced each output."

### DefraDB Capabilities
DefraDB provides powerful versioning features that make this possible:

- **Time Travel Queries**: Query any document at any historical state via CID
- **`_commits` API**: Full commit history with delta payloads
- **Content-Addressed Storage**: Every version has a unique CID (SHA256 hash)
- **Automatic History**: No explicit versioning needed - every mutation is tracked

```graphql
# Query prompt at specific version
query { Prompt(cid: "bafyrei...", dockey: "prompt-123") { text } }

# Get full history
query { _commits(docID: "prompt-123") { cid, height, delta } }
```

## Decision

### Phased Implementation

**Phase 1: Config in Database**
- Move all runtime config from `~/.shelf/config.yaml` to DefraDB
- Global-only hierarchy (no book-level overrides yet)
- Auto-seed defaults on first run
- Web UI at `/settings` for viewing/editing

**Phase 2: Prompt Linking (Traceability)**
- Every LLM/agent call records which prompt CID was used
- Link calls to the specific prompt version that produced output
- Enable "what prompt produced this?" queries

**Phase 3: Prompts in Database**
- Move all prompts from code to DefraDB
- Hierarchical: global defaults, book-level overrides
- Book settings page for editing prompts per-book
- Full version history via DefraDB time travel

### Schema Design

#### Config Collection (Phase 1)
```graphql
type Config {
  key: String! @index(unique: true)    # Hierarchical path
  value: JSON!                          # Flexible value storage
  description: String                   # Human-readable description
}
```

**Config Keys (hierarchical paths):**
```
providers.openrouter.api_key
providers.openrouter.base_url
providers.openrouter.rate_limit
providers.mistral.enabled
processing.default_model
processing.default_temperature
processing.max_tokens
processing.workers.ocr
processing.workers.agent
```

#### Prompt Collection (Phase 3)
```graphql
type Prompt {
  key: String! @index(unique: true)    # Hierarchical path
  text: String!                         # The prompt text
  description: String                   # What this prompt does
  variables: [String!]                  # Template variables used
}
```

**Prompt Keys (hierarchical paths):**
```
agents.toc_finder.system
agents.toc_finder.user
agents.toc_extractor.system
stages.ocr.blend_prompt
stages.structure.label_prompt
```

#### Book Overrides (Phase 3)
```graphql
type BookPromptOverride {
  book: Book!                           # Reference to book
  promptKey: String!                    # Which prompt to override
  promptCID: String                     # Reference specific version, OR
  customText: String                    # Custom text for this book
}
```

**Resolution Order:** Book override (if exists) > Global default

#### LLM Call Tracking (Phase 2)
```graphql
type LLMCall {
  id: String! @index(unique: true)
  timestamp: DateTime!
  book: Book                            # Optional book context
  page: Page                            # Optional page context
  job: Job                              # Job that triggered this
  promptCID: String!                    # CID of prompt used
  promptKey: String!                    # Which prompt (for context)
  model: String!
  temperature: Float!
  inputTokens: Int!
  outputTokens: Int!
  latencyMs: Int!
  response: String!                     # The LLM response
  toolCalls: [JSON!]                    # For agent calls
}
```

### Key Design Decisions

#### 1. Single Prompt Collection with CID References
Instead of separate GlobalPrompt and BookPrompt collections, use one Prompt collection. Book overrides reference specific CIDs:
- Global default = current version of the prompt
- Book override = reference to a specific CID OR custom text

This leverages DefraDB's versioning naturally.

#### 2. Hierarchical Path Keys
Keys like `agents.toc_finder.system` provide:
- Clear namespacing
- Easy filtering (`agents.*` for all agent prompts)
- Self-documenting structure

#### 3. Auto-Seed on First Run
When no config/prompts exist in DB:
1. Load defaults from embedded Go constants
2. Create documents in DefraDB
3. Continue with DB as source of truth

#### 4. Reset = Copy Default
"Reset to default" copies the current global default as a new version (preserving history) rather than deleting the override.

#### 5. CID = Content
Since CIDs are content-addressed (deterministic hash), storing `promptCID` IS storing the exact prompt text. No need for redundant text snapshots.

### UI Design

#### Global Settings Page (`/settings`)
- Dedicated route for all global configuration
- Grouped by category (Providers, Processing, etc.)
- Edit values inline
- Changes create new versions (tracked via DefraDB)

#### Book Settings Page (`/books/:id/settings`) (Phase 3)
- Shows resolved values (merged global + book overrides)
- Visual indicators: "inherited" vs "overridden"
- Edit prompts with full text editor
- History view showing all versions

### Migration Path

#### Phase 1: Config Migration
1. On server start, check if Config collection has entries
2. If empty, seed from current `~/.shelf/config.yaml` (if exists) or embedded defaults
3. Config reads go through DefraDB, not file
4. Eventually remove config file support

#### ~/.shelf Folder Reassessment
The `~/.shelf` folder currently holds:
- `config.yaml` - moves to DB
- DefraDB data directory - stays
- Logs - stays (or moves to DB?)

May need `shelf init` command for first-time setup UX.

### Implementation Order

#### Phase 1: Config in DB
1. Define Config schema in DefraDB
2. Create `internal/config/db_config.go` - config from DefraDB
3. Add seeding logic for defaults
4. Update all config reads to use DB
5. Add `/settings` endpoint + UI
6. Deprecate file-based config

#### Phase 2: Prompt Linking
1. Define LLMCall schema in DefraDB
2. Modify `internal/providers/` to record calls
3. Add promptCID field (placeholder until Phase 3)
4. Add query endpoints for call history
5. UI for viewing call history per book/page

#### Phase 3: Prompts in DB
1. Define Prompt and BookPromptOverride schemas
2. Extract prompts from code to embedded defaults
3. Add seeding logic
4. Modify agents/stages to load prompts from DB
5. Add book settings UI
6. Add prompt editing UI with history view

## Consequences

### Positive
- Full traceability: every output linked to exact prompt version
- Easy experimentation: edit prompts without recompiling
- Per-book customization: handle edge cases without code changes
- Complete history: DefraDB tracks all changes automatically
- Single source of truth: DB holds all runtime state

### Negative
- More complexity: config/prompts now in DB layer
- Migration required: existing users need one-time migration
- DB dependency: can't run without DefraDB (already true)

### Risks
- Performance: prompt lookups add latency (mitigate: cache hot prompts)
- Complexity: hierarchical resolution logic can have bugs
- UX: need good UI for prompt editing (power user tool, acceptable)

## References
- DefraDB Time Travel: `/Users/johnzampolin/go/src/github.com/sourcenetwork/defradb/docs/website/guides/time-traveling-queries.md`
- DefraDB Commits API: `_commits(docID: "...") { cid, height, delta }`
- Master tracking issue: #119
