# Batch Throughput Foundation — Design (Sub-project A)

**Date:** 2026-06-27
**Status:** Design — approved, pending spec review
**Author:** Jack Zampolin + Claude

## Context

The pipeline now runs end-to-end on self-hosted inference (Chandra OCR + Qwen3.6
on the DGX Sparks, DefraDB v1.0). The goal is to **rapidly ingest a whole corpus
of books whenever needed** and have them processed unattended. That larger effort
decomposes into three sub-projects, built in order:

- **A — Batch throughput foundation** *(this spec)*: corpus prep + book-aware
  scheduling so many queued books drain the fixed Spark budget efficiently and
  finish in order.
- **B — EPUB export at scale**: verify/auto-run the existing EPUB/Storyteller
  export as a final stage. Its own spec/plan cycle.
- **C — Audiobooks / TTS**: stand up local TTS serving + wire + batch. Infra-gated
  on freeing the RTX Pro 6000 box. Its own spec/plan cycle.

The queueing/resume/retry primitives already exist and are **not** rebuilt here:
- Work-unit-centric scheduler: each `process_book` job emits work units that route
  to shared per-provider worker pools (`internal/jobs/provider_pool.go`).
- Pools bound the real Spark load (per-provider `max_concurrency`, rate limits),
  so any number of queued books only ever drives the configured concurrency.
- Jobs are resumable (DefraDB is source of truth); per-unit retry exists.

## Goal

Two general capabilities (no book-specific hardcoding):

1. **Multi-part stitching** — merge `<title>-N.pdf` scan parts into one book before
   ingest so multi-part titles aren't fragmented.
2. **Book-aware priority scheduling** — share the fixed OCR/LLM capacity across
   queued books with a *priority-ordered, full-utilization* policy: earlier-submitted
   books win the shared slots, idle slots are filled by later books' ready work, so
   books finish roughly in submission order while the Sparks stay saturated.

## Scope

**In scope (A):** multi-part stitching; book-aware priority scheduling; documenting
the existing `max_concurrency` as the capacity knob.

**Out of scope:** a bulk ingest+start command; down-Spark / wedged-provider
resilience; EPUB (B); TTS (C). (These were explicitly deprioritized for A.)

## Existing code this builds on

- `internal/jobs/job.go`: `WorkUnit{ ID, Type, Provider, JobID, Priority int, ... }`
  — `Priority` is "higher = processed first".
- `internal/jobs/priority_queue.go`: `PriorityQueue` (container/heap); priority
  levels `PriorityLow=0`, `PriorityNormal=10` (page ops), `PriorityHigh=20`
  (book-level ops); `PriorityForStage(stageOrKey)` assigns the stage tier.
- `internal/jobs/provider_pool.go`: per-provider pool with a dispatcher that pulls
  the highest-priority unit from its `PriorityQueue`, rate-limits, and hands to
  workers. **Priority today is stage-based only — not book-aware**, which is why
  books interleave instead of finishing in order.
- `internal/jobs/scheduler_routing.go`: `enqueueUnits(jobID, units)` routes units
  to pools.
- `internal/jobs/scheduler_submit.go`: job submission; jobs persist to DefraDB with
  a `created_at` (the stable, restart-safe ordering source).
- `internal/ingest/`: PDF ingestion (page extraction).

## Design

### Component 1 — Multi-part PDF stitching (general)

A pure grouping function over a set of input PDF paths:

- **Group key:** strip a trailing numeric suffix matching a configurable regex
  (default `[-_]\d+$`) from the filename stem. Files with no match form their own
  single-item group (pass through unchanged).
- **Order:** within a group, sort parts ascending by the captured number.
- **Output:** for each group, a merged PDF named after the group key, ready for the
  normal `books ingest`. Single-file groups are ingested as-is (no copy needed).

Boundaries:
- `internal/ingest/stitch.go`: `func GroupParts(paths []string, pattern *regexp.Regexp) []BookParts`
  where `BookParts{ Name string; Parts []string }` — pure, no I/O, fully unit-testable.
- `func StitchPDF(parts []string, out string) error` — merges page-by-page using the
  existing PDF library already in `internal/ingest` (reuse; do not add a new dep
  unless none supports merge — then prefer `pdfcpu`).
- CLI surface: a `--stitch` flag on `books ingest` (accepts a directory): groups,
  stitches multi-part groups into a temp/work dir, then ingests each resulting book.
  Single command, general over any directory.

### Component 2 — Book-aware priority scheduling (core)

Make scheduling order books by submission while preserving intra-book stage tiers,
using the existing priority machinery.

1. **Submission sequence (general, restart-safe):** order books by their
   `process_book` job's persisted `created_at` (DefraDB). Earlier `created_at` →
   higher priority. Using the persisted timestamp (not an in-memory counter) keeps
   ordering stable across server restarts/resumes.

2. **Composite priority via tuple comparator (chosen mechanism):**
   - Add `BookSeq int64` to `WorkUnit` (the job's `created_at` as unix-nanos; 0 = unset/highest-tier-agnostic).
   - Extend `PriorityQueue`'s `Less(i, j)` to compare as a tuple:
     1. **Book order first:** smaller `BookSeq` ranks higher (earlier book wins).
        `BookSeq == 0` (unset) is treated as the **latest** book (sorts after all real
        books) so missing/unset ordering degrades to lowest book-priority and never
        preempts a real book. In practice every `process_book` OCR/LLM unit carries a
        real `created_at`, so 0 is only a safety baseline.
     2. **Then stage tier:** within the same book, higher `Priority` (the existing
        `PriorityForStage` tier) wins — preserving today's book-level-before-page-level
        behavior unchanged.
   - `enqueueUnits` sets `unit.BookSeq` from the submitting job's `created_at` (looked
     up once per job and cached on the in-memory job record to avoid a DB hit per unit).

3. **Full-utilization property:** each pool's dispatcher always pops the
   highest-ranked *ready* unit. When the earliest book has ready units for that pool,
   they run; when it doesn't (e.g. it's mid-LLM-stage with no OCR units), the pool
   pops a later book's units → idle capacity is filled. No head-of-line blocking; the
   Sparks stay saturated; books complete in submission order.

Per-pool note: each provider pool has its own queue, so book-ordering applies
independently within the OCR pool and the LLM pool. Both drain earlier books first,
so a book finishes (across OCR and LLM) before later books, modulo natural stage
overlap.

### Component 3 — Concurrency budget (already a knob)

The global Spark capacity — "how many concurrent OCR / LLM requests" — is the
existing per-provider `max_concurrency` (32/32 today) plus `rate_limit`, set in
`~/.shelf/config.yaml` and threaded through to the pools. No new work; this spec
documents it as *the* capacity dial that the priority scheduler then allocates
across books. Tuning it up/down changes total Spark load; the scheduler decides who
gets the slots.

## Error handling

- Stitcher: a corrupt/unreadable part fails that group with a clear error and skips
  to the next group (one bad book doesn't abort the batch); report skipped groups.
- Scheduler: `BookSeq` is advisory ordering only — a missing/zero value degrades to
  current stage-only behavior (safe default), never errors. Comparator must be a
  strict weak ordering (stable, total) to keep the heap valid.

## Testing

- **Stitcher (pure):** grouping (multi-part, single-file passthrough, mixed),
  numeric ordering incl. `-1`/`-10` (not lexical), custom pattern, empty dir,
  non-PDF skip. `StitchPDF` page-count = sum of parts on a small fixture.
- **Priority comparator (unit):** earlier `BookSeq` outranks later regardless of
  stage tier; within equal `BookSeq`, higher stage tier wins; `BookSeq==0` baseline
  behavior; ordering is total/stable.
- **Scheduler (integration-style):** submit two books; assert the earlier book's
  ready units are dispatched before the later book's, and that when the earlier book
  has no ready units for a pool the later book's units run (full utilization). Reuse
  the existing scheduler test harness + mock providers.

## Risks / open items

- **PDF merge library:** confirm the lib already in `internal/ingest` supports
  page-level merge; if not, add `pdfcpu` (pure-Go) rather than shelling out.
- **Comparator change touches the hot path:** the heap `Less` runs per push/pop;
  keep it cheap (int64 + int compares) and covered by tests to avoid a subtle
  ordering bug stalling a pool.
- **Cross-pool fairness:** OCR and LLM queues order independently; this is correct
  for "finish earlier books first" but means a book's LLM stage and a later book's
  OCR can run concurrently (desired — full utilization). Documented, not a bug.

## Non-goals

No changes to the per-book stage logic, provider implementations, DefraDB schema, or
the existing retry/resume. No bulk-ingest command, no wedged-provider handling (a
later resilience effort if needed).
