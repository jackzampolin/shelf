# Large-File Breakup & TTS Package Merge — Design

**Date:** 2026-07-01
**Status:** Approved
**Scope:** All non-test Go files over 400 lines (ADR 003), plus deduplication of the `tts_generate` / `tts_generate_openai` twin packages.

## Goals

1. No multi-concept file over 400 lines; a developer can find "everything about X" in one predictably named file.
2. Eliminate the ~60% duplication between the two TTS job packages while keeping both persisted job-type strings working.
3. Zero behavior change for everything except the TTS merge. Zero import-path changes for the split tiers (same-package moves); the TTS merge is the sole exception — it deletes `internal/jobs/tts_generate_openai` and updates its four importers (`internal/jobcfg/builder.go`, `internal/server/server.go`, `internal/server/endpoints/books_audio.go`, `internal/server/endpoints/tts_config.go`). No compatibility facade: all call sites are in-repo and a hollow package would defeat the decluttering goal.

## Principles

- **One concept per file governs.** Files that are a single cohesive concept (one provider client, one event loop, one builder) stay intact even above 400 lines (Tier 3). ADR 003's line limit applies to multi-concept files.
- **Splits are pure moves** within the same package: no renames, no signature changes, no exported-symbol changes. Verified by `go build ./...`, full test suite, and reviewing the diff for anything that isn't a move.
- **Follow each package's existing naming scheme** (`state_*.go`, `load_*.go`, `scheduler_*.go`, one file per endpoint family, one file per provider).

## Tier 1 — Multi-concept splits (13 files)

### internal/jobs/common/

| Current | New files (concept) |
|---|---|
| `state.go` (1,951) | `state_page.go` (PageState + methods), `state_operation.go` (OpStatus, OperationState + deprecated op wrappers), `state_book.go` (BookState struct, constructor, CID/write tracking), `state_book_pages.go` (page accessors, provider progress), `state_toc.go` (ToC found/range/entries, ToC-link progress), `state_linked_entries.go` (linked entries, structure phase counters, body range), `state_finalize.go` (finalize types + accessors, page-pattern context), `state_chapter.go` (ChapterState, StructureState, chapter mgmt), `state_agent.go` (AgentState + run summaries), `state_metadata.go` (BookMetadata storage/lazy-load), `state_cost.go` (cost tracking) |
| `load.go` (1,458) | `load.go` (LoadBookConfig/Result + LoadBook orchestrator), `load_prompts.go`, `load_pages.go`, `load_operation_state.go`, `load_toc_entries.go`, `load_agent_states.go`, `load_finalize.go`, `load_structure.go`, `load_db_helpers.go` (metadata/cost/agent-run lazy loaders) |
| `state_persist_toc.go` (592) | `state_persist_toc.go` (record + finder result + extract complete), `state_persist_toc_entries.go` (batch upsert, linking), `state_persist_toc_discovery.go` (discovered entries, gap fixes, resort), `state_persist_toc_cleanup.go` (bulk delete/clear) |
| `state_store_memory.go` (602) | `state_store_memory.go` (struct, constructor, Send/SendSync/SendManySync), `state_store_memory_versioned.go` (UpsertWithVersion/UpdateWithVersion), `state_store_memory_query.go` (CID gen, query parsing, filter matching, applyOp), `state_store_memory_testctl.go` (doc access, relations, reset, error injection) |
| `structure_helpers.go` (525) | `structure_prompts.go` (prompts + JSON schemas), `structure_classify.go` (classify prompt building + signals), `structure_text.go` (strip/merge/clean/edit text utilities; includes the small shared types) |
| `reset.go` (504) | `reset.go` (ResetOperation types, validation, ResetFrom orchestrator + cascade), `reset_ops.go` (resetOp, resetAllOcr), `reset_cleanup.go` (agent-state/ToC-entry/link cleanup) |
| `page_reader_impl.go` (405) | `page_reader_impl.go` (core accessors + DB load), `page_reader_preload.go` (batch preloading), `page_reader_headings.go` (heading-aware access) |

| `persist.go` (530) | `persist.go` (sink send helpers, op-state, book status, structure/finalize/toc-link async wrappers) + `persist_agent_state.go` (agent-state persist/delete, ~300 lines) |

Left alone in this package: `state_persist_book.go` (669) and `state_persist_chapters.go` (534) are already organized as one persistence concern per section with no better seam; revisit only if they grow.

### internal/jobs/process_book/job/

| Current | New files |
|---|---|
| `finalize.go` (1,874) | `finalize.go` (phase orchestration + completion), `finalize_pattern.go`, `finalize_discover.go` (incl. chapter-finder agent ops), `finalize_validate.go` (incl. gap-investigator agent ops), `finalize_helpers.go` (pattern loaders, converters, estimators) |
| `structure.go` (1,411) | `structure.go` (StartStructurePhase orchestration), `structure_build.go` (skeleton build + persistence), `structure_extract.go`, `structure_classify.go`, `structure_polish.go`, `structure_completion.go` (finalization, validation, stats) |
| `link_toc.go` (880) | `link_toc.go` (batch orchestration), `link_toc_agents.go` (entry-finder agent lifecycle), `link_toc_structure.go` (book structure/back-matter analysis), `link_toc_execution.go` (completion handler, resolution, cleanup) |

`job.go` (680) is the cohesive job lifecycle — leave (Tier 3).

### internal/server/endpoints/

- `books_audio.go` (867) → `books_audio_generate.go` + `books_audio_status.go` (two distinct endpoints).
- `jobs_status_detailed.go` (891) → keep endpoint + types; extract the ~400-line `getDetailedStatus` into per-stage builders in `jobs_status_detailed_build.go` (`buildMetadataStatus`, `buildOcrProgress`, `buildTocStatus`, `buildStructureStatus`, `loadAgentLogs`). This is the one split that refactors a function body, so it is NOT covered by the pure-moves guarantee: it gets its own commit, preceded by a response-shape test (golden JSON against a seeded in-memory store) that must pass unchanged before and after the extraction.

### internal/agents/toc_entry_finder/tools/

- `ocr_evidence.go` (573) → `ocr_evidence.go` (types + public entry points), `ocr_evidence_extract.go` (evidence loaders/extractors), `ocr_evidence_text.go` (normalization/matching utilities).

## Tier 2 — Single-seam light splits (4 files)

| File | Cut |
|---|---|
| `providers/chandra_ocr.go` (685) | `chandra_ocr.go` (client, config, ProcessImage) + `chandra_parse.go` (layout-HTML parsing and text cleanup) |
| `providers/registry.go` (617) | `registry.go` (registry type + register/get/list) + `registry_config.go` (RegistryConfig, NewRegistryFromConfig, Reload) |
| `defra/client.go` (549) | `client.go` (client, health, Execute, CRUD) + `client_versioned.go` (CreateWithVersion/UpdateWithVersion/UpsertWithVersion) |
| `jobs/provider_pool.go` (656) | `provider_pool.go` (pool struct, dispatcher, workers, submit) + `provider_pool_process.go` (the LLM/OCR/TTS process switch + metrics recording) |

## Tier 3 — Cohesive, intentionally left over 400

`process_book/job/job.go` (680), `endpoints/prompts.go` (562), `endpoints/books_export_storyteller.go` (498), `endpoints/voices.go` (430), `providers/mistral.go` (444), `providers/elevenlabs_tts.go` (406), `jobs/scheduler.go` (488), `agent/agent.go` (561), `defra/sink.go` (534), `defra/docker.go` (428), `epub/media_overlay.go` (461), `server/server.go` (503), `config/store.go` (408). Each is one concept; splitting would manufacture fragments. Future audits should apply the one-concept test before flagging these.

## TTS merge

Merge `tts_generate_openai/` into `tts_generate/`, parameterized by a small strategy interface. The provider abstraction already supports this: `providers.TTSRequest` carries both `Instructions` (OpenAI) and `PreviousRequestIDs` (ElevenLabs); `TTSResult` carries `RequestID`.

**What stays different (the strategy):**
- Queueing model: ElevenLabs sequential-per-chapter (request-ID stitching for prosody); OpenAI parallel-all-segments + offset recalculation on completion.
- Segmentation: paragraphs (ElevenLabs) vs sentence splitting with 4,096-char cap (OpenAI, `sentences.go`).
- Work-unit request fields: `PreviousRequestIDs` vs `Instructions`.
- Format defaults/support: `mp3_44100_128` + 7 variants vs `mp3` only.
- Concatenate task name constants (both preserved: `concatenate_chapter`, `concatenate_chapter_openai`).

**Package shape (all files <400):**

```
internal/jobs/tts_generate/
├── tts_generate.go   # JobType constants (both), Config, NewJob, format normalization
├── types.go          # unified Chapter/SegmentResult/ChapterProgress/AudioState/Job
├── strategy.go       # providerStrategy interface + elevenLabsStrategy + openAIStrategy
├── job.go            # Start/OnComplete shells delegating to strategy; shared retry/failure paths
├── persist.go        # the identical DB operations (ensureBookAudioRecord, saveAudioSegment, ...)
├── segmentation.go   # splitIntoParagraphs + splitIntoSentences (moved from sentences.go)
├── handler.go        # concatenate handler, both task names
└── ffmpeg.go         # unchanged
```

**Compatibility invariants:**
- Both job-type strings `"tts-generate"` and `"tts-generate-openai"` remain registered (they are persisted in DefraDB job records). `jobcfg.TTSJobFactory` and `jobcfg.OpenAITTSJobFactory` both remain, constructing the unified Job with the matching strategy.
- **The unified Job carries its persisted job-type string and reports it everywhere the packages hard-code it today**: `Type()` (`types.go:347` / `types.go:298`), `MetricsFor().Stage` (`types.go:363` / `types.go:314`), per-segment and concatenate work-unit metrics, and the CPU concat task name (`concatenate_chapter` vs `concatenate_chapter_openai`). A merged job must never report `tts-generate` for an OpenAI job or vice versa — that would corrupt resume routing and cost attribution.
- **Strategy selection is pinned to the persisted job-type string, not to current config defaults.** Today `TTSJobFactory` reads `defaults.tts_provider` (`jobcfg/builder.go:213`); after the merge, a resumed `tts-generate` job always gets the sequential/stitching strategy and `tts-generate-openai` always gets the parallel/offset strategy, regardless of what `defaults.tts_provider` currently says. Provider *client* lookup may still come from config; orchestration strategy may not.
- State documents (AudioState et al.) keep their field names; unified struct is the union (`Instructions`, `RequestIDSequence` used only by their provider).
- Existing tests move with the code; add strategy-level tests asserting, per strategy: `Type()`, `MetricsFor().Stage`, segment work-unit metrics stage, concat work-unit metrics stage, and CPU task name all match the persisted job type; ElevenLabs queues exactly one segment per chapter initially, OpenAI queues all; OpenAI recalculates offsets; ElevenLabs threads request IDs and handles stale-ID fallback.

## Execution order & verification

1. `jobs/common` splits (one commit) → 2. `process_book/job` splits → 3. endpoints/agents/Tier 2 → 4. TTS merge → 5. doc sync (CLAUDE.md tree, audit-checklist key files, note Tier 3 rationale in ADR 003).
- After each step: `go build ./...`, `go vet ./...`, `make test`; diff review confirming moves-only (steps 1–3).
- The live server is unaffected until redeploy; the TTS merge lands last and is the only step needing real review.

## Out of scope

- ADR 010 SendSync→async migration (separate effort).
- Any endpoint/CLI surface changes.
- Splitting Tier 3 files or amending ADR 003's threshold.
