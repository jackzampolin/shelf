# 8. Delete Stage Abstraction

**Date:** 2025-12-29

**Status:** Accepted

## Context

The `Stage` interface implied a linear pipeline (stage 1 → stage 2 → stage 3) when in reality:

1. There was only one "stage" (`page_processing`) doing 7 distinct operations
2. The name "stage" suggested sequence, but execution was really "jobs that process schemas"
3. We wanted flexibility to compose operations into different jobs (e.g., "rerun just ToC", "add OCR source")

The real mental model is: **schemas + jobs that mutate them + history in DB**

## Decision

Delete the `Stage` interface entirely. Jobs are the primary abstraction.

### What Was Deleted

- `internal/pipeline/stage.go` - Stage interface
- `internal/pipeline/registry.go` - Stage registry
- `internal/pipeline/registry_test.go` - Registry tests
- `svcctx.PipelineRegistry` - Context extractor

### What Was Moved

| From | To |
|------|-----|
| `internal/pipeline/stages/page_processing/` | `internal/jobs/process_pages/` |
| `internal/pipeline/prompts/` | `internal/prompts/` |
| `internal/pipeline/agents/` | `internal/agents/` |

### What Was Refactored

**Endpoints:**
- `POST /api/pipeline/start/{book_id}` → `POST /api/jobs/start/{book_id}`
- `GET /api/pipeline/status/{book_id}` → `GET /api/jobs/status/{book_id}`
- `--stage` flag → `--job-type` flag

**CLI:**
- `shelf api pipeline start/status` → `shelf api jobs start/status`

**Server:**
- Removed pipeline registry creation
- Job factory registered directly with process_pages package

## New Structure

```
internal/
├── jobs/
│   ├── job.go              # Job interface (unchanged)
│   ├── scheduler.go        # Scheduler (unchanged)
│   └── process_pages/      # Was: pipeline/stages/page_processing/
│       ├── process_pages.go  # NewJob(), GetStatus(), JobFactory()
│       └── job/              # Job implementation
├── prompts/                # Was: pipeline/prompts/
│   ├── blend/
│   ├── label/
│   ├── metadata/
│   └── extract_toc/
├── agents/                 # Was: pipeline/agents/
│   └── toc_finder/
└── schema/                 # DefraDB schemas (unchanged)
```

## API Changes

### Starting a Job

```bash
# Old
shelf api pipeline start <book_id> --stage page-processing

# New
shelf api jobs start <book_id> --job-type process-pages
```

### Checking Status

```bash
# Old
shelf api pipeline status <book_id> --stage page-processing

# New
shelf api jobs status <book_id> --job-type process-pages
```

## Benefits

1. **Simpler** - No unnecessary abstraction layer
2. **Clearer naming** - "Job" is what users trigger, not "Stage"
3. **Extensible** - Add new job types (rerun-toc, add-ocr) by adding to the switch statement
4. **Less code** - Deleted ~500 lines of registry/interface code

## Future Work

Add focused job types:
- `rerun-toc` - Re-run ToC finding and extraction
- `add-ocr` - Add additional OCR provider to existing pages
- `build-structure` - Build paragraph structure from ToC

Each is just a new case in the job type switch with its own `NewJob()` constructor.
