# Large-File Breakup & TTS Merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split every multi-concept Go file over 400 lines into focused same-package files, and merge the duplicated `tts_generate` / `tts_generate_openai` packages into one strategy-parameterized package.

**Architecture:** Tasks 1–14 are pure code moves within existing packages (no import-path, API, or behavior changes), each verified by build + full tests. Task 10/11 is the one sanctioned refactor (`getDetailedStatus`), gated by a golden response-shape test. Tasks 15–17 perform the TTS merge behind compatibility invariants pinned to persisted job-type strings.

**Tech Stack:** Go 1.x, standard library testing, DefraDB via `internal/defra`, existing `internal/testutil` + `fakeDefra` httptest patterns.

**Spec:** `docs/superpowers/specs/2026-07-01-large-file-breakup-design.md` — read it before starting any task.

## Global Constraints

- **Pure moves (Tasks 1–9, 12–14):** cut whole declarations (type/func/method/const/var + their doc comments) from the source file and paste them verbatim into the named destination file in the SAME package. Do not rename, reorder parameters, change visibility, or edit bodies. New files start with the same package clause; imports are whatever the compiler demands (run `gofmt -w` after each file).
- **Verification after EVERY task:** `go build ./...` && `go vet ./...` && `make test` — all green before committing. For move tasks also run `git diff --stat` and confirm only the listed files changed.
- **One commit per task**, message format from CLAUDE.md (type prefix, body, `Co-Authored-By: Claude <noreply@anthropic.com>` after the Claude Code line).
- **Symbol maps are authoritative by NAME, not line number** — line numbers drift; locate each symbol with grep before moving.
- **The live 25-book run is unaffected** (server runs a compiled binary), but do not restart or redeploy the server as part of this plan.
- All new files must land under 400 lines. After the final task, `find internal cmd -name "*.go" ! -name "*_test.go" -exec wc -l {} + | awk '$1>400'` must list only the Tier 3 files named in the spec.

---

### Task 1: Split `internal/jobs/common/state.go` (1,951 → 11 files)

**Files:**
- Modify: `internal/jobs/common/state.go` (emptied and deleted at the end)
- Create: 11 files per the map below
- Test: existing `internal/jobs/common` tests (no new tests; moves only)

**Interfaces:** No signature changes. Every moved symbol keeps its exact name; all callers are in-package or already import `common`.

- [ ] **Step 1: Move symbols into new files per this map** (locate each by name with `grep -n "func \|^type " internal/jobs/common/state.go`):

| New file | Symbols |
|---|---|
| `state_page.go` | `PageState` struct, `NewPageState`, and every `func (p *PageState)` method (OcrComplete, MarkOcrComplete, AllOcrDone, SetExtractDone, IsExtractDone, SetOcrMarkdown, GetOcrMarkdown, IsOcrMarkdownSet, GetOcrResult, GetPageDocID, SetPageDocID, GetPageCID, SetPageCID, GetHeadings, SetHeadings, IsDataLoaded, SetDataLoaded, SetOcrMarkdownWithHeadings, PopulateFromDBResult, GetHeader, SetHeader, GetFooter, SetFooter) |
| `state_operation.go` | `OpStatus` + `String()`, `OperationState`, `NewOperationState`, its methods (Start, Complete, Fail, Reset, IsStarted, IsDone, IsFailed, IsComplete, CanStart, GetRetries), and the deprecated BookState op wrappers (`MetadataStart/Complete/Fail/Reset`, `TocFinderStart/...`, `TocExtractStart/...`, `TocLinkStart/...`, `TocFinalizeStart/...`, `StructureStart/...`) |
| `state_book.go` | `BookState` struct, `NewBookState`, CID/write tracking: `GetBookCID`, `SetBookCID`, `GetTocCID`, `SetTocCID`, `GetOperationCID`, `SetOperationCID`, `TrackWrite`, `trackCIDLocked`, `GetCID` |
| `state_book_pages.go` | `GetPage`, `GetOrCreatePage`, `GetPageAtCID`, `ForEachPage`, `CountPages`, `CountOcrPages`, `AllPagesComplete`, `AllPagesOcrComplete`, `ConsecutivePagesComplete`, `ProviderProgress` type, `GetProviderProgress` |
| `state_toc.go` | `GetTocFound`, `SetTocFound`, `GetTocPageRange`, `SetTocPageRange`, `SetTocResult`, `GetPrompt`, `GetPromptCID`, `GetTocEntries`, `SetTocEntries`, `GetUnlinkedTocEntries`, `GetTocLinkProgress`, `SetTocLinkProgress`, `IncrementTocLinkEntriesDone` |
| `state_linked_entries.go` | `GetLinkedEntries`, `SetLinkedEntries`, `HasLinkedEntries`, `SetStructurePhase`, `GetStructurePhase`, `SetStructureProgress`, `GetStructureProgress`, `IncrementStructurePolished`, `IncrementStructurePolishFailed`, `GetBodyRange`, `SetBodyRange`, `GetBodyStart`, `GetBodyEnd` |
| `state_finalize.go` | types `FinalizePatternResult`, `DiscoveredPattern`, `ExcludedRange`, `EntryToFind`, `FinalizeGap`, `PagePatternContext`, `DetectedChapter`; accessors `GetFinalizePhase`, `SetFinalizePhase`, `GetFinalizePatternResult`, `SetFinalizePatternResult`, `GetEntriesToFind`, `SetEntriesToFind`, `AppendEntryToFind`, `GetEntriesToFindCount`, `GetFinalizeGaps`, `SetFinalizeGaps`, `AppendFinalizeGap`, `GetFinalizeGapsCount`, `GetFinalizeProgress`, `SetFinalizeProgress`, `IncrementFinalizeEntriesComplete`, `IncrementFinalizeEntriesFound`, `IncrementFinalizeGapsComplete`, `IncrementFinalizeGapsFixes`, `GetFinalizeEntriesTotalCount`, `SetFinalizeEntriesTotal`, `GetFinalizeGapsTotalCount`, `SetFinalizeGapsTotal`, `GetFinalizePagePatternCtx`, `SetFinalizePagePatternCtx` |
| `state_chapter.go` | `ChapterState` + `Copy` + `NewChapterState`, `StructureState`, `GetStructureChapters`, `SetStructureChapters`, `GetStructureClassifications`, `SetStructureClassifications`, `GetStructureClassifyPending`, `SetStructureClassifyPending`, `GetChapterByEntryID`, `UpdateChapter`, `GetStructureClassifyReasonings`, `SetStructureClassifyReasonings` |
| `state_agent.go` | `AgentState`, `IsValidAgentType`, `NewAgentState`, `AgentStateKey`, `GetAgentState`, `SetAgentState`, `RemoveAgentState`, `GetAllAgentStates`, `ClearAgentStates`, `AgentRunSummary`, `AddAgentRun`, `GetAgentRuns`, `GetAgentRunCount`, `SetAgentRuns`, `AgentRunsLoaded`, `GetAgentRunsWithLazyLoad` |
| `state_metadata.go` | `BookMetadata` type, `GetBookMetadata`, `SetBookMetadata`, `GetBookMetadataWithLazyLoad`, `GetBookTitle` |
| `state_cost.go` | `AddCost`, `GetTotalCost`, `GetCostByStage`, `GetCostsByStage`, `SetCosts`, `CostsLoaded`, `GetTotalCostWithLazyLoad` |

Any package-level consts/vars in `state.go` move with the type they serve. When `state.go` is empty, `git rm internal/jobs/common/state.go`.

- [ ] **Step 2: Format and build**

Run: `gofmt -w internal/jobs/common/ && go build ./... && go vet ./internal/jobs/common/`
Expected: no output, exit 0.

- [ ] **Step 3: Run package + full tests**

Run: `go test ./internal/jobs/common/ && make test`
Expected: `ok github.com/jackzampolin/shelf/internal/jobs/common`, all packages pass.

- [ ] **Step 4: Verify sizes and moves-only diff**

Run: `wc -l internal/jobs/common/state_*.go | sort -rn | head -5` (all < 400) and `git diff --stat` (only `internal/jobs/common/state*.go` listed).

- [ ] **Step 5: Commit**

```bash
git add internal/jobs/common && git commit -m "refactor: split jobs/common/state.go by state domain (ADR 003)

Pure move: 1,951-line file split into 11 focused files
(state_page, state_operation, state_book, state_book_pages, state_toc,
state_linked_entries, state_finalize, state_chapter, state_agent,
state_metadata, state_cost). No signature or behavior changes.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Split `internal/jobs/common/load.go` (1,458 → 9 files)

**Files:** Modify `internal/jobs/common/load.go`; create 8 siblings.

**Interfaces:** No signature changes.

- [ ] **Step 1: Move symbols per this map:**

| New file | Symbols |
|---|---|
| `load.go` (keeps) | `LoadBookConfig`, `LoadBookResult`, `LoadBook` |
| `load_prompts.go` | `ResolvePrompts` |
| `load_pages.go` | `LoadPageStates` |
| `load_operation_state.go` | `loadOpStateFromData`, `boolsToOpState`, `LoadBookOperationState` |
| `load_toc_entries.go` | `LoadTocEntries`, `loadTocEntriesViaStore`, `numericToInt` |
| `load_agent_states.go` | `LoadAgentStates` |
| `load_finalize.go` | `LoadFinalizeState` |
| `load_structure.go` | `LoadStructureChapters` |
| `load_db_helpers.go` | `loadBookMetadataFromDB`, `loadBookCostsFromDB`, `loadAgentRunsFromDB` |

- [ ] **Step 2: Format, build, vet** — `gofmt -w internal/jobs/common/ && go build ./... && go vet ./internal/jobs/common/` → clean.
- [ ] **Step 3: Test** — `go test ./internal/jobs/common/ && make test` → all pass.
- [ ] **Step 4: Verify** — `wc -l internal/jobs/common/load*.go` all < 400; `git diff --stat` only load files.
- [ ] **Step 5: Commit** — `refactor: split jobs/common/load.go by loaded domain (ADR 003)` (same body/attribution style as Task 1).

---

### Task 3: Split `persist.go` and `state_persist_toc.go`

**Files:** Modify `internal/jobs/common/persist.go`, `internal/jobs/common/state_persist_toc.go`; create `persist_agent_state.go`, `state_persist_toc_entries.go`, `state_persist_toc_discovery.go`, `state_persist_toc_cleanup.go`.

- [ ] **Step 1: Move symbols:**

| New file | Symbols |
|---|---|
| `persist.go` (keeps) | `SendToSinkSync`, `SendTracked`, `SendManyTracked`, `PersistOpState`, `PersistOpStateAsync`, `PersistBookStatus`, `PersistBookStatusAsync`, `PersistStructurePhaseAsync`, `PersistFinalizePhaseAsync`, `PersistFinalizeProgressAsync`, `PersistTocLinkProgressAsync` |
| `persist_agent_state.go` | `PersistAgentState`, `PersistAgentStates`, `DeleteAgentStateByAgentIDAsync`, `DeleteAgentStateByAgentID`, `DeleteAgentStatesForType` |
| `state_persist_toc.go` (keeps) | `tocEntryResult`, `PersistTocRecord`, `PersistTocFinderResult`, `PersistTocExtractComplete` |
| `state_persist_toc_entries.go` | `PersistTocEntries`, `PersistTocEntryLink` |
| `state_persist_toc_discovery.go` | `PersistDiscoveredEntry`, `PersistGapFix`, `sortUpdate`, `PersistEntryResort` |
| `state_persist_toc_cleanup.go` | `DeleteAllTocEntries`, `ClearAllTocEntryLinks` |

- [ ] **Step 2–4:** format/build/vet, `go test ./internal/jobs/common/ && make test`, size + diff checks (as Task 1 steps 2–4).
- [ ] **Step 5: Commit** — `refactor: split jobs/common persist and toc persistence files (ADR 003)`.

---

### Task 4: Split `state_store_memory.go` and `structure_helpers.go`

**Files:** Modify both; create `state_store_memory_versioned.go`, `state_store_memory_query.go`, `state_store_memory_testctl.go`, `structure_prompts.go`, `structure_classify.go`, `structure_text.go`.

- [ ] **Step 1: Move symbols:**

| New file | Symbols |
|---|---|
| `state_store_memory.go` (keeps) | `MemoryStateStore` struct, `NewMemoryStateStore`, `Execute`, `Send`, `SendSync`, `SendManySync`, `String` |
| `state_store_memory_versioned.go` | `UpsertWithVersion`, `UpdateWithVersion` |
| `state_store_memory_query.go` | `generateCID`, `matchesFilterMap`, `applyOp`, `filterCondition`, `parseSimpleQuery`, `matchesFilters` |
| `state_store_memory_testctl.go` | `GetDoc`, `SetDoc`, `WriteCount`, `GetWrites`, `SetRelation`, `SetBookDoc`, `SetTocDoc`, `SetPageDoc`, `Reset`, `SetErrorOnCollection`, `SetErrorOnDocID`, `SetErrorAfterNWrites`, `ClearErrors` |
| `structure_prompts.go` | the prompt/schema consts at the top of `structure_helpers.go`, `ClassifyJSONSchema`, `PolishJSONSchema`, `BuildPolishPrompt` |
| `structure_classify.go` | `BuildClassifyPrompt`, `buildClassifySnippet`, `classifyContentSignals`, `looksNumberedListLine`, plus shared types `PageText`, `TextEdit`, `ClassifyResult`, `PolishResult` |
| `structure_text.go` | `StripHeaderFooter`, `normalizeLine`, `MergeChapterPages`, `determineJoin`, `CleanPageText`, `isPageNumberLine`, `CountWords`, `ApplyEdits` |

Delete `structure_helpers.go` when empty (`git rm`).

- [ ] **Step 2–4:** format/build/vet, tests, size + diff checks.
- [ ] **Step 5: Commit** — `refactor: split memory state store and structure helpers (ADR 003)`.

---

### Task 5: Split `reset.go` and `page_reader_impl.go`

**Files:** Modify both; create `reset_ops.go`, `reset_cleanup.go`, `page_reader_preload.go`, `page_reader_headings.go`.

- [ ] **Step 1: Move symbols:**

| New file | Symbols |
|---|---|
| `reset.go` (keeps) | `ResetOperation`, `ValidResetOperations`, `IsValidResetOperation`, `ResetFrom`, `resetOpWithCascade` |
| `reset_ops.go` | `resetOp`, `resetAllOcr` |
| `reset_cleanup.go` | `deleteAgentStatesForTypeViaStore`, `deleteTocEntries`, `clearTocEntryLinks` |
| `page_reader_impl.go` (keeps) | `GetPageData`, `GetOcrMarkdown`, `GetOcrMarkdownWithPageFurniture`, `splitPageFurnitureLines`, `GetTotalPages`, `GetBookID`, `loadPageDataFromDB` |
| `page_reader_preload.go` | `PreloadPages` |
| `page_reader_headings.go` | `GetPagesWithHeadings`, `GetPagesWithHeadingsFiltered` |

- [ ] **Step 2–4:** format/build/vet, tests, size + diff checks.
- [ ] **Step 5: Commit** — `refactor: split jobs/common reset and page reader files (ADR 003)`.

---

### Task 6: Split `internal/jobs/process_book/job/finalize.go` (1,874 → 5 files)

**Files:** Modify `finalize.go`; create `finalize_pattern.go`, `finalize_discover.go`, `finalize_validate.go`, `finalize_helpers.go` in the same directory.

- [ ] **Step 1: Move symbols:**

| New file | Symbols |
|---|---|
| `finalize.go` (keeps) | phase constants/types at top (`PagePatternContext` local type, `candidateHeading`), `StartFinalizePhase`, `checkFinalizeValidateCompletion`, `completeFinalizePhase` |
| `finalize_pattern.go` | `CreateFinalizePatternWorkUnit`, `HandleFinalizePatternComplete`, `processFinalizePatternResult`, `generateEntriesToFind` |
| `finalize_discover.go` | `transitionToFinalizeDiscover`, `createFinalizeDiscoverWorkUnits`, `createChapterFinderAgentWithState`, `createChapterFinderWorkUnit`, `HandleFinalizeDiscoverComplete` |
| `finalize_validate.go` | `transitionToFinalizeValidate`, `findFinalizeGaps`, `createFinalizeGapWorkUnits`, gap-investigator agent creation funcs, `HandleFinalizeGapComplete` |
| `finalize_helpers.go` | `loadExistingPatternResults`, `buildPagePatternContext`, converter/estimator helpers at the file tail |

- [ ] **Step 2–4:** `gofmt -w internal/jobs/process_book/job/ && go build ./... && go vet ./internal/jobs/process_book/...`; `go test ./internal/jobs/... && make test`; size + diff checks.
- [ ] **Step 5: Commit** — `refactor: split process_book finalize stage by phase (ADR 003)`.

---

### Task 7: Split `internal/jobs/process_book/job/structure.go` (1,411 → 6 files)

**Files:** Modify `structure.go`; create `structure_build.go`, `structure_extract.go`, `structure_classify.go`, `structure_polish.go`, `structure_completion.go`.

- [ ] **Step 1: Move symbols:**

| New file | Symbols |
|---|---|
| `structure.go` (keeps) | `StartStructurePhase` and its immediate orchestration helpers |
| `structure_build.go` | `buildChapterSkeleton`, hierarchy helpers, skeleton persistence (upsert, identity matching, stale deletion) |
| `structure_extract.go` | `extractAllChapters`, `extractChapterPages`, extract persistence |
| `structure_classify.go` | classify transition, classify work-unit creation, classify handler + result processing, classify persistence |
| `structure_polish.go` | polish transition, per-chapter polish work-unit creation, polish handler + result processing, polish persistence |
| `structure_completion.go` | phase completion, structure finalization, validation helpers, stats computation |

(Names in this file mirror the phases; locate exact functions with `grep -n "^func" internal/jobs/process_book/job/structure.go` and assign each to its phase file by name prefix/subject.)

- [ ] **Step 2–4:** format/build/vet, tests, size + diff checks.
- [ ] **Step 5: Commit** — `refactor: split process_book structure stage by phase (ADR 003)`.

---

### Task 8: Split `internal/jobs/process_book/job/link_toc.go` (880 → 4 files)

**Files:** Modify `link_toc.go`; create `link_toc_agents.go`, `link_toc_structure.go`, `link_toc_execution.go`.

- [ ] **Step 1: Move symbols:**

| New file | Symbols |
|---|---|
| `link_toc.go` (keeps) | `CreateLinkTocWorkUnits`, `createMoreLinkTocWorkUnits`, progress tracking |
| `link_toc_agents.go` | entry-finder agent lifecycle (create/restore/work-unit gen), single-entry work-unit creation + retry helpers |
| `link_toc_structure.go` | book-structure helpers: back-matter detection, patterns, back-matter label inference |
| `link_toc_execution.go` | `HandleLinkTocComplete`, agent execution, `resolveTocLinkEntry`, `cleanupLinkTocAgentStateWithMode`, conversions |

- [ ] **Step 2–4:** format/build/vet, tests, size + diff checks.
- [ ] **Step 5: Commit** — `refactor: split process_book link_toc stage (ADR 003)`.

---

### Task 9: Split `internal/server/endpoints/books_audio.go` (867 → 2 files)

**Files:** Rename/modify `books_audio.go`; create `books_audio_status.go`.

- [ ] **Step 1:** `git mv internal/server/endpoints/books_audio.go internal/server/endpoints/books_audio_generate.go`. Move `GetAudioStatusEndpoint` (type, Route, RequiresInit, handler, Command) and `AudioStatusResponse` + any status-only helpers into new `books_audio_status.go`. `GenerateAudioEndpoint`, `DownloadChapterAudioEndpoint` (if present in this file), request/response types for generation stay in `books_audio_generate.go`.
- [ ] **Step 2–4:** format/build/vet; `go test ./internal/server/... && make test`; both files < 400; diff shows only these two files.
- [ ] **Step 5: Commit** — `refactor: split books_audio endpoint file by endpoint (ADR 003)`.

---

### Task 10: Golden response-shape test for detailed job status

**Files:**
- Test: `internal/server/endpoints/jobs_status_detailed_test.go` (create)

**Interfaces:**
- Consumes: `getDetailedStatus(ctx context.Context, client *defra.Client, bookID string, agentLogLimit int) (*DetailedJobStatusResponse, error)` (current signature at `jobs_status_detailed.go:336`)
- Produces: `TestGetDetailedStatus_ResponseShape` — the gate for Task 11.

- [ ] **Step 1: Write the test.** Follow the `fakeDefra` pattern from `run_summary_test.go`: an `httptest.Server` that routes on the GraphQL request body and returns canned JSON for every query `getDetailedStatus` issues (Book, Job, Page, TocEntry, Chapter, AgentLog — grep the function for `client.Execute`/query strings and stub each; include a book with OCR partially complete, a linked ToC entry, one chapter, one agent log so every builder path is exercised). Then:

```go
func TestGetDetailedStatus_ResponseShape(t *testing.T) {
	server := fakeDetailedStatusDefra(t) // canned responses as described above
	defer server.Close()

	client := defra.NewClient(server.URL)
	resp, err := getDetailedStatus(context.Background(), client, "book-A", 5)
	if err != nil {
		t.Fatalf("getDetailedStatus: %v", err)
	}
	got, err := json.MarshalIndent(resp, "", "  ")
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	golden := filepath.Join("testdata", "detailed_status_book_a.json")
	if os.Getenv("UPDATE_GOLDEN") == "1" {
		if err := os.WriteFile(golden, got, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	want, err := os.ReadFile(golden)
	if err != nil {
		t.Fatalf("read golden (run with UPDATE_GOLDEN=1 first): %v", err)
	}
	if !bytes.Equal(bytes.TrimSpace(got), bytes.TrimSpace(want)) {
		t.Errorf("response shape changed:\n--- want\n%s\n--- got\n%s", want, got)
	}
}
```

- [ ] **Step 2: Generate the golden file** — `UPDATE_GOLDEN=1 go test ./internal/server/endpoints/ -run TestGetDetailedStatus_ResponseShape` then re-run WITHOUT the env var: PASS. Inspect `testdata/detailed_status_book_a.json` by hand — it must contain non-trivial metadata/OCR/ToC/structure/agent-log sections (not all zero values); if sections are empty, extend the canned data until each builder path produces output.
- [ ] **Step 3: Commit** — `test: golden response-shape test for detailed job status endpoint`.

---

### Task 11: Extract `getDetailedStatus` stage builders

**Files:**
- Modify: `internal/server/endpoints/jobs_status_detailed.go`
- Create: `internal/server/endpoints/jobs_status_detailed_build.go`

**Interfaces:**
- Consumes: the golden test from Task 10 (must pass unchanged — do NOT regenerate the golden file in this task).
- Produces: unexported builders `buildMetadataStatus`, `buildOcrProgress`, `buildTocStatus`, `buildStructureStatus`, `loadAgentLogs`, each taking `(ctx context.Context, client *defra.Client, bookID string, resp *DetailedJobStatusResponse)` (add extra params only where the existing code requires, e.g. `agentLogLimit int` for `loadAgentLogs`) and returning `error`.

- [ ] **Step 1:** Cut the sequential sections of `getDetailedStatus` into the five builders in `jobs_status_detailed_build.go`, keeping statements byte-identical inside each extracted body; `getDetailedStatus` becomes the short sequence of builder calls with the same early-return error handling order as today.
- [ ] **Step 2:** `go test ./internal/server/endpoints/ -run TestGetDetailedStatus_ResponseShape` → PASS with the Task 10 golden file untouched (`git status testdata/` clean).
- [ ] **Step 3:** `go build ./... && go vet ./... && make test` → green; both files < 400 lines.
- [ ] **Step 4: Commit** — `refactor: extract detailed-status stage builders (ADR 003)` noting the golden-test gate in the body.

---

### Task 12: Split `internal/agents/toc_entry_finder/tools/ocr_evidence.go` (573 → 3 files)

**Files:** Modify `ocr_evidence.go`; create `ocr_evidence_extract.go`, `ocr_evidence_text.go`.

- [ ] **Step 1: Move symbols:** `ocr_evidence.go` keeps `PageEvidence`, `ScanWindow`, `AnalyzePageEvidence`, `ValidateCandidatePage`. `ocr_evidence_extract.go` gets the evidence loaders/extractors (`pageEvidence`, `previousPageEvidence`, `extractPageHeaders`, `extractSectionHeaders`, labeled-block extraction). `ocr_evidence_text.go` gets normalization/strip/match text utilities.
- [ ] **Step 2–4:** format/build/vet; `go test ./internal/agents/... && make test`; sizes + diff.
- [ ] **Step 5: Commit** — `refactor: split toc_entry_finder ocr_evidence tool (ADR 003)`.

---

### Task 13: Tier 2 provider splits (`chandra_ocr.go`, `registry.go`)

**Files:** Modify `internal/providers/chandra_ocr.go`, `internal/providers/registry.go`; create `internal/providers/chandra_parse.go`, `internal/providers/registry_config.go`.

- [ ] **Step 1:** Move the Chandra layout-HTML parsing layer (`parseChandraLayoutHTML`, `collectBlocks`, `parseBlocks`, HTML/markdown converters, text cleanup) into `chandra_parse.go`; client/config/ProcessImage/accessors stay. Move `RegistryConfig` types, `NewRegistryFromConfig`, `Reload`, `applyConfig` into `registry_config.go`; the registry type with register/get/list stays.
- [ ] **Step 2–4:** format/build/vet; `go test ./internal/providers/ && make test`; sizes + diff.
- [ ] **Step 5: Commit** — `refactor: split chandra parsing and registry config (ADR 003)`.

---

### Task 14: Tier 2 splits (`defra/client.go`, `jobs/provider_pool.go`)

**Files:** Modify `internal/defra/client.go`, `internal/jobs/provider_pool.go`; create `internal/defra/client_versioned.go`, `internal/jobs/provider_pool_process.go`.

- [ ] **Step 1:** Move `CreateWithVersion`, `UpdateWithVersion`, `UpsertWithVersion` (+ their private helpers used only by them) into `client_versioned.go`. Move the `process()` method (the LLM/OCR/TTS switch) and its metrics-recording helpers into `provider_pool_process.go`; pool struct, constructor, dispatcher, worker, Submit, Status stay.
- [ ] **Step 2–4:** format/build/vet; `go test ./internal/defra/ ./internal/jobs/ && make test`; sizes + diff.
- [ ] **Step 5: Commit** — `refactor: split defra versioned writes and pool processing (ADR 003)`.

---

### Task 15: TTS merge A — strategy scaffolding inside `tts_generate`

**Files:**
- Create: `internal/jobs/tts_generate/strategy.go`, `internal/jobs/tts_generate/persist.go`, `internal/jobs/tts_generate/segmentation.go`
- Modify: `internal/jobs/tts_generate/tts_generate.go`, `types.go`, `job.go`, `handler.go`
- Test: `internal/jobs/tts_generate/strategy_test.go` (create)

**Interfaces:**
- Produces (used by Tasks 16–17):

```go
const (
	JobTypeElevenLabs = "tts-generate"        // persisted in DefraDB job records
	JobTypeOpenAI     = "tts-generate-openai" // persisted in DefraDB job records
)

// providerStrategy captures every per-provider orchestration difference.
type providerStrategy interface {
	Provider() string       // pinned provider client name: "elevenlabs" | "openai"
	JobType() string        // the persisted job-type string
	ConcatTaskName() string // "concatenate_chapter" | "concatenate_chapter_openai"
	DefaultFormat() string
	NormalizeFormat(format string) string
	SegmentText(text string) []string
	// InitialWorkUnits: ElevenLabs returns the first incomplete segment per
	// chapter (sequential stitching); OpenAI returns all incomplete segments.
	InitialWorkUnits(j *Job) []jobs.WorkUnit
	// OnSegmentComplete persists the finished segment and returns follow-up
	// units (ElevenLabs: next segment with request-ID threading; OpenAI:
	// offset recalculation then concat when the chapter completes).
	OnSegmentComplete(ctx context.Context, j *Job, res jobs.WorkResult) ([]jobs.WorkUnit, error)
}

func strategyForJobType(jobType string) (providerStrategy, error) // errors on unknown type

// NewJob gains the job type; Config drops nothing.
func NewJob(ctx context.Context, jobType string, cfg Config, bookID string) (*Job, error)
```

- `Job` gains fields `jobType string`, `strategy providerStrategy`. `Type()` returns `j.jobType`; `MetricsFor().Stage` uses `j.jobType`; segment/concat work-unit metrics use `j.jobType` as stage.

- [ ] **Step 1: Write failing strategy tests** in `strategy_test.go`:

```go
func TestStrategyIdentity(t *testing.T) {
	cases := []struct {
		jobType, provider, concat string
	}{
		{JobTypeElevenLabs, "elevenlabs", "concatenate_chapter"},
		{JobTypeOpenAI, "openai", "concatenate_chapter_openai"},
	}
	for _, c := range cases {
		s, err := strategyForJobType(c.jobType)
		if err != nil {
			t.Fatalf("%s: %v", c.jobType, err)
		}
		if s.Provider() != c.provider || s.JobType() != c.jobType || s.ConcatTaskName() != c.concat {
			t.Errorf("%s: got (%s,%s,%s)", c.jobType, s.Provider(), s.JobType(), s.ConcatTaskName())
		}
	}
	if _, err := strategyForJobType("bogus"); err == nil {
		t.Error("expected error for unknown job type")
	}
}

func TestJobReportsPersistedType(t *testing.T) {
	for _, jt := range []string{JobTypeElevenLabs, JobTypeOpenAI} {
		j := newTestJob(t, jt) // helper: minimal Job with one chapter, one segment
		if j.Type() != jt {
			t.Errorf("Type() = %s, want %s", j.Type(), jt)
		}
		if m := j.MetricsFor(); m.Stage != jt {
			t.Errorf("MetricsFor().Stage = %s, want %s", m.Stage, jt)
		}
	}
}

func TestElevenLabsQueuesOneSegmentPerChapter(t *testing.T) {
	j := newTestJobWithChapters(t, JobTypeElevenLabs, 2 /*chapters*/, 3 /*segments each*/)
	units := j.strategy.InitialWorkUnits(j)
	if len(units) != 2 {
		t.Fatalf("got %d initial units, want 2 (one per chapter)", len(units))
	}
}
```

Run: `go test ./internal/jobs/tts_generate/ -run 'TestStrategy|TestJobReports|TestElevenLabs' -v` → FAIL (undefined symbols).

- [ ] **Step 2: Implement inside `tts_generate` only** (do not touch the openai package yet):
  - Add the constants, interface, `strategyForJobType` (returning `elevenLabsStrategy` for `JobTypeElevenLabs`; `JobTypeOpenAI` returns a placeholder error until Task 16 — the test's OpenAI cases are added in Task 16; keep Task 15's tests ElevenLabs-only plus the identity-table entry gated accordingly, or implement a minimal `openAIStrategy` stub that fully satisfies identity methods, which is simpler and keeps the test table intact).
  - `elevenLabsStrategy` implements the interface by MOVING existing logic: `splitIntoParagraphs` → `segmentation.go`; the Start() queueing loop → `InitialWorkUnits`; the segment-completion block of `OnComplete` (request-ID storage, `getPreviousRequestIDs`, `clearRequestIDSequence`, `shouldDisableRequestStitching`, next-segment queueing) → `OnSegmentComplete`.
  - Move the shared DB operations (`ensureBookAudioRecord`, `saveAudioSegment`, `saveChapterAudio`, `updateBookAudioComplete`, `updateBookAudioFailed`, `markBookAudioFailed`, `ConcatenateChapterAudio`, `formatToExtension`) into `persist.go` unchanged.
  - Thread `jobType` through `NewJob`/`NewJobFromState`; update in-package callers and existing tests to pass `JobTypeElevenLabs`.
- [ ] **Step 3:** `go test ./internal/jobs/tts_generate/ -v` → all PASS (old + new). `go build ./... && make test` → green (the openai package still builds untouched).
- [ ] **Step 4: Commit** — `refactor: introduce TTS provider strategy inside tts_generate`.

---

### Task 16: TTS merge B — port the OpenAI strategy

**Files:**
- Create: `internal/jobs/tts_generate/strategy_openai.go`
- Modify: `internal/jobs/tts_generate/segmentation.go` (add sentence splitting), `types.go` (union state: add `Instructions` to `AudioState`/`Config`), `strategy_test.go`, `handler.go` (register/route both concat task names)
- Copy tests: port `tts_generate_openai/sentences_test.go` cases into `internal/jobs/tts_generate/segmentation_test.go`

**Interfaces:**
- Consumes: Task 15's `providerStrategy`, `strategyForJobType`, `persist.go` helpers.
- Produces: fully functional `openAIStrategy` selected by `strategyForJobType(JobTypeOpenAI)`.

- [ ] **Step 1: Write failing tests** (add to `strategy_test.go`):

```go
func TestOpenAIQueuesAllSegments(t *testing.T) {
	j := newTestJobWithChapters(t, JobTypeOpenAI, 2, 3)
	units := j.strategy.InitialWorkUnits(j)
	if len(units) != 6 {
		t.Fatalf("got %d initial units, want 6 (all segments)", len(units))
	}
}

func TestOpenAISegmentCap(t *testing.T) {
	s, _ := strategyForJobType(JobTypeOpenAI)
	long := strings.Repeat("A sentence here. ", 600) // > 4096 chars
	for i, seg := range s.SegmentText(long) {
		if len(seg) > 4096 {
			t.Errorf("segment %d is %d chars, exceeds OpenAI 4096 cap", i, len(seg))
		}
	}
}
```

Run → FAIL.

- [ ] **Step 2: Implement by MOVING from `tts_generate_openai`** (copy code; the old package stays in place until Task 17): `splitIntoSentences` + helpers → `segmentation.go`; parallel Start() queueing → `openAIStrategy.InitialWorkUnits`; OpenAI OnComplete segment block (`recalculateChapterOffsets`, `updateAudioSegmentOffset`, concat queueing) → `OnSegmentComplete`; `Instructions` threading into the TTS work-unit request; OpenAI format normalization (`mp3` only) into `NormalizeFormat`/`DefaultFormat`.
- [ ] **Step 3:** `go test ./internal/jobs/tts_generate/ -v` → PASS including ported sentence tests. `go build ./... && make test` → green.
- [ ] **Step 4: Commit** — `feat: add OpenAI strategy to unified tts_generate package`.

---

### Task 17: TTS merge C — pairing validation, rewire importers, delete the twin

**Files:**
- Modify: `internal/jobs/tts_generate/tts_generate.go` (validation + resume cross-check), `internal/jobcfg/builder.go`, `internal/server/server.go`, `internal/server/endpoints/books_audio_generate.go` (was books_audio.go), `internal/server/endpoints/tts_config.go`
- Delete: `internal/jobs/tts_generate_openai/` (entire package)
- Test: extend `internal/jobs/tts_generate/strategy_test.go`; update `internal/jobcfg` tests if present

**Interfaces:**
- Consumes: `strategyForJobType`, `NewJob(ctx, jobType, cfg, bookID)`.
- Produces: `jobcfg.TTSJobFactory` → `tts_generate.NewJob(ctx, tts_generate.JobTypeElevenLabs, ...)`; `jobcfg.OpenAITTSJobFactory` → `tts_generate.NewJob(ctx, tts_generate.JobTypeOpenAI, ...)`. Both scheduler registrations in `server.go` keep their exact type strings.

- [ ] **Step 1: Write failing pairing tests:**

```go
func TestNewJobRejectsMismatchedProvider(t *testing.T) {
	_, err := NewJob(context.Background(), JobTypeElevenLabs,
		Config{TTSProvider: "openai"}, "book-1")
	if err == nil {
		t.Fatal("want pairing error, got nil")
	}
}

func TestNewJobDefaultsProviderFromJobType(t *testing.T) {
	// Empty provider resolves to the strategy's pinned provider, ignoring
	// defaults.tts_provider entirely.
	j := newTestJob(t, JobTypeElevenLabs) // constructs with Config{TTSProvider: ""}
	if got := j.State.TTSProvider; got != "elevenlabs" {
		t.Errorf("TTSProvider = %q, want elevenlabs", got)
	}
}

func TestResumeRejectsMismatchedBookAudioProvider(t *testing.T) {
	// Seed a BookAudio record with provider "openai", then resume as
	// tts-generate (elevenlabs). Job must fail with a pairing error, not run.
	// Use the fake-defra httptest pattern to serve the BookAudio query.
}
```

- [ ] **Step 2: Implement:** in `NewJob`: resolve strategy from jobType; `cfg.TTSProvider == ""` → `strategy.Provider()`; mismatch → error. In the resume/load path (`loadBookAudio` caller): if persisted `BookAudio.provider` is non-empty and != `strategy.Provider()` → fail the job with a descriptive error. Update `jobcfg.TTSJobFactory` to stop consulting `defaults.tts_provider` for strategy/provider selection (it may still read voice/format/instructions settings); update `OpenAITTSJobFactory` likewise with `JobTypeOpenAI`.
- [ ] **Step 3: Rewire and delete:** update the four importers (`jobcfg/builder.go`, `server/server.go`, `endpoints/books_audio_generate.go`, `endpoints/tts_config.go`) to use `tts_generate.JobTypeOpenAI` etc.; `git rm -r internal/jobs/tts_generate_openai`.
- [ ] **Step 4:** `go build ./... && go vet ./... && make test` → green. `grep -rn "tts_generate_openai" --include="*.go" internal/ cmd/` → no hits. All files in `internal/jobs/tts_generate/` < 400 lines.
- [ ] **Step 5: Commit** — `refactor: merge tts_generate_openai into tts_generate via provider strategies` with a body covering the invariants (both job-type strings registered, type/metrics/task-name reporting, provider-strategy pairing, BookAudio.provider resume check).

---

### Task 18: Docs sync and final sweep

**Files:**
- Modify: `CLAUDE.md`, `docs/audit-checklist.md`, `docs/decisions/003-file-organization.md`

- [ ] **Step 1:** `find internal cmd -name "*.go" ! -name "*_test.go" -exec wc -l {} + | awk '$1>400 && $2!="total"' | sort -rn` — every remaining file must be on the spec's Tier 3 list; investigate and fix any that isn't.
- [ ] **Step 2:** Update CLAUDE.md's architecture tree: `tts_generate/` comment becomes "TTS audio generation (ElevenLabs + OpenAI strategies)"; delete the `tts_generate_openai/` line; jobs list in the Remember section drops `tts-generate-openai` as a separate package (the job TYPE still exists — keep it in the LLM-calling jobs list). Update `docs/audit-checklist.md` package table's `jobs/` key files if they changed.
- [ ] **Step 3:** Append a short "Cohesion exception" note to ADR 003: single-concept files (one provider client, one event loop, one builder) may exceed 400 lines when splitting would fragment one concept; cite the Tier 3 list in the spec.
- [ ] **Step 4:** `make test` one final time → green. Commit — `docs: sync docs after file breakup and TTS merge`.

---

## Self-Review Notes

- Spec coverage: Tier 1 (14 files) → Tasks 1–9, 12 (state, load, persist, persist_toc, memory store, structure_helpers, reset, page_reader, finalize, structure, link_toc, books_audio, jobs_status_detailed, ocr_evidence). Tier 2 (4 files) → Tasks 13–14. Golden-test gate → Tasks 10–11. TTS merge + invariants → Tasks 15–17. Docs/ADR note → Task 18.
- The scout symbol maps informing Tasks 1–8 were generated from the current tree; executors must resolve symbols by NAME and flag (not silently skip) any listed symbol that no longer exists.
- Task 15 note: prefer implementing the minimal `openAIStrategy` identity stub in Task 15 so `TestStrategyIdentity`'s full table passes; Task 16 replaces the stub's behavior methods with the real ported logic.
