# Debugging process_book

## Table of Contents
- [API Endpoints for Debugging](#api-endpoints-for-debugging)
- [Direct DefraDB Queries](#direct-defradb-queries)
- [Debug Configuration](#debug-configuration)
- [Common Issues](#common-issues)
- [Adding Logging](#adding-logging)

---

## API Endpoints for Debugging

### Job Status

```bash
# Detailed job status with all stage progress
shelf api jobs status <book-id>

# List all jobs (filter by status/type)
shelf api jobs list
shelf api jobs list --status running --type process-book

# Get specific job
shelf api jobs get <job-id>
```

### Book and Page Data

```bash
# Book details (includes metadata, pattern analysis)
shelf api books get <book-id>

# List pages with processing status
# Returns: page_num, ocr_complete, blend_complete, label_complete
GET /api/books/{book_id}/pages

# Get specific page (full data including labels, OCR results)
GET /api/books/{book_id}/pages/{page_num}

# Get page image
GET /api/books/{book_id}/pages/{page_num}/image
```

### Agent Logs

```bash
# List agent logs for a job
shelf api agent-logs list --job-id <job-id>

# Get specific agent log (full conversation)
shelf api agent-logs get <log-id>
```

### LLM Calls and Metrics

```bash
# List LLM call history
shelf api llmcalls list

# Metrics summary (cost, tokens)
shelf api metrics summary

# Cost for specific book
shelf api books cost <book-id>
```

### Health and Status

```bash
shelf api health   # Basic health
shelf api ready    # Includes DefraDB status
shelf api status   # Detailed system status with providers
```

---

## Direct DefraDB Queries

State is stored in DefraDB and can be queried directly via GraphQL.

### Book State

```graphql
{
  Book(filter: {_docID: {_eq: "<book-id>"}}) {
    title
    author
    page_count
    status

    # Metadata processing
    metadata_started
    metadata_complete
    metadata_failed
    metadata_retries

    # Structure
    structure_started
    structure_complete
    structure_failed

    # Relationships
    toc { _docID }
  }
}
```

### Page State

```graphql
{
  Page(filter: {book_id: {_eq: "<book-id>"}}, order: {page_num: ASC}) {
    page_num

    # Processing status
    extract_complete
    ocr_complete
    blend_complete
    label_complete

    # Results
    blend_markdown
    blend_confidence

    # Labels
    page_number_label
    running_header
    content_type
    is_chapter_start
    is_toc_page

    # OCR results per provider
    ocr_results {
      provider
      text
      confidence
    }
  }
}
```

### ToC State

```graphql
{
  ToC(filter: {book_id: {_eq: "<book-id>"}}) {
    toc_found
    start_page
    end_page

    # Processing state
    finder_started
    finder_complete
    finder_failed
    finder_retries

    extract_started
    extract_complete
    extract_failed

    link_started
    link_complete
    link_failed

    finalize_started
    finalize_complete
    finalize_failed

    # Entries
    entries {
      title
      expected_page
      actual_page
      level
    }
  }
}
```

### Agent Runs (Completed Logs)

```graphql
{
  AgentRun(filter: {job_id: {_eq: "<job-id>"}}) {
    agent_type
    created_at
    completed_at
    success
    # Full conversation log is in messages field
  }
}
```

### Agent State (In-Progress Agents)

For agents currently running (not yet completed):

```graphql
{
  AgentState(filter: {book_id: {_eq: "<book-id>"}}) {
    _docID
    agent_id
    agent_type
    entry_doc_id
    entry_key
    created_at
    complete
  }
}
```

**Note:** Agent states are only persisted at creation (async). If an agent is mid-conversation and the server crashes, the state record exists but won't have conversation history. The agent restarts from scratch on resume.

### LLM Calls

```graphql
{
  LLMCall(filter: {book_id: {_eq: "<book-id>"}}, order: {created_at: DESC}) {
    provider
    model
    stage
    page_num
    input_tokens
    output_tokens
    cost_usd
    created_at
  }
}
```

---

## Debug Configuration

### Enable Agent Debug Logs

Agent logs are only saved when `DebugAgents` is true:

```go
cfg := process_book.Config{
    DebugAgents: true,  // Saves agent conversation logs to DefraDB
}
```

**Propagation path:**
```
Config.DebugAgents
  → LoadBook(cfg.DebugAgents)
  → BookState.DebugAgents
  → agents.NewAgent(cfg.Debug)
  → Agent.SaveLog(ctx) when done
```

### Viewing Debug Logs

When enabled, agent logs contain:
- Full system/user/assistant message history
- Tool calls and tool responses
- Final result
- Timing information

```bash
# Via CLI
shelf api agent-logs list --job-id <job-id>
shelf api agent-logs get <log-id>

# Direct query
{
  AgentRun(filter: {job_id: {_eq: "<job-id>"}}) {
    agent_type
    messages
    result
  }
}
```

---

## Common Issues

### Stage Not Starting

**Check preconditions via DB:**
```graphql
# For label (needs blend + pattern analysis)
{
  Page(filter: {book_id: {_eq: "<id>"}}) {
    page_num
    blend_complete
    label_complete
  }
}
{
  Book(filter: {_docID: {_eq: "<id>"}}) {
    pattern_analysis_complete
  }
}
```

**Check OperationState:**
- `*_started = false` and `*_complete = false` → Can start
- `*_started = true` and `*_complete = false` → In progress
- `*_complete = true` → Done

### Work Unit Not Completing

```bash
# Check provider health
shelf api status

# Check job status for active work units
shelf api jobs get <job-id>
```

### State Lost After Restart

**Cause:** Async writes (`sink.Send`) not flushed before crash.

**Check:** Compare in-memory expectation vs DB:
```graphql
{
  Page(filter: {book_id: {_eq: "<id>"}, page_num: {_eq: 5}}) {
    blend_complete
    blend_markdown
  }
}
```

**Prevention:** Use `sink.SendSync()` for critical operations.

### Job Stuck After Restart

**Cause:** In-progress operations not reset.

**Check book-level operations:**
```graphql
{
  Book(filter: {_docID: {_eq: "<id>"}}) {
    metadata_started
    metadata_complete
  }
}
```

If `started=true` and `complete=false`, the operation was interrupted. Job's `Start()` should detect and reset these.

**Check agent states:**
```graphql
{
  AgentState(filter: {book_id: {_eq: "<id>"}}) {
    agent_id
    agent_type
    complete
  }
}
```

Agent states with `complete=false` represent interrupted agents. On resume, these agents restart from scratch (no conversation history preserved).

**Clean up stale agent states:**
Agent states are deleted by `agent_id` on completion. Stale states from crashes can be manually deleted:
```graphql
mutation {
  delete_AgentState(filter: {book_id: {_eq: "<id>"}})
}
```

### Missing Data on Page

**Check OCR results exist:**
```graphql
{
  Page(filter: {book_id: {_eq: "<id>"}, page_num: {_eq: 10}}) {
    ocr_complete
    ocr_results {
      provider
      text
    }
  }
}
```

---

## Adding Logging

### In OnComplete Handler

```go
func (j *Job) OnComplete(ctx context.Context, result jobs.WorkResult) {
    logger := svcctx.LoggerFrom(ctx)

    info, ok := j.GetWorkUnit(result.WorkUnitID)
    if !ok {
        logger.Error("unknown work unit", "id", result.WorkUnitID)
        return
    }

    logger.Debug("work unit complete",
        "type", info.UnitType,
        "page", info.PageNum,
        "success", result.Success,
        "error", result.Error,
    )
}
```

### Work Unit Flow Trace

```
1. CreateXWorkUnit → "creating work unit type=X page=N"
2. RegisterWorkUnit → "registered unit id=UUID"
3. (Worker executes)
4. OnComplete → "work unit complete id=UUID success=true/false"
5. HandleXComplete → "handling X page=N"
6. RemoveWorkUnit → "removed unit id=UUID"
```

### Failure Logging

```go
if !result.Success {
    logger.Warn("work unit failed",
        "type", info.UnitType,
        "page", info.PageNum,
        "retry", info.RetryCount,
        "max", MaxRetries,
        "error", result.Error,
    )
}
```

---

## Future: API Exposure

Some debugging currently requires direct DB queries. Consider exposing:

- `GET /api/books/{id}/toc` - ToC state and entries
- `GET /api/books/{id}/pattern-analysis` - Pattern analysis results
- `GET /api/jobs/{id}/work-units` - Active work units
- Query filters for pages (e.g., `?blend_complete=false`)
