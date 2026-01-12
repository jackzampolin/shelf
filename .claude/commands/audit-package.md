# Package Audit: $ARGUMENTS

Deep audit of a single package in `internal/`.

## Usage

```
/audit-package jobs
/audit-package pipeline
/audit-package server
```

## Instructions

1. Identify the target package from arguments
2. Create TodoWrite for package-specific checks
3. Read ALL files in the package
4. Check against relevant ADRs
5. ASK before making fixes

## Package Audit Checklist

### Structure
- [ ] Package purpose is clear from name
- [ ] Each file has one concept (ADR 003)
- [ ] No file >400 lines (ADR 003)
- [ ] Naming follows conventions (ADR 004)
- [ ] No TODO/FIXME comments (ADR 001)

### Dependencies
- [ ] Imports are appropriate (no cycles)
- [ ] Lower packages don't import higher
- [ ] External deps are justified

### Services Context (ADR 007)
- [ ] Uses `svcctx.*From(ctx)` extractors
- [ ] No services passed via constructor (except init)
- [ ] Context propagation is correct

### DefraDB Usage (ADR 005)
- [ ] State changes go through DefraDB
- [ ] Uses DefraSink appropriately (Send vs SendSync)
- [ ] No filesystem state

### Job Patterns (ADR 006)
- [ ] Work flows through job system
- [ ] Rate limiting respected
- [ ] Metrics recorded

### Tests
- [ ] Critical paths have tests
- [ ] Tests use mocks (not real APIs)
- [ ] Test files are `*_test.go`

## Package-Specific Checks

### agent/
- Tool registration pattern
- Multi-turn conversation handling
- Error recovery

### api/
- Endpoint interface implementation
- Client error handling
- Route registration

### config/
- Hot reload mechanism
- Schema validation
- Default handling

### defra/
- Docker lifecycle management
- Client connection handling
- Sink batching logic

### home/
- Directory creation
- Path resolution

### ingest/
- Book intake flow
- Validation

### jobs/
- Scheduler orchestration
- Worker rate limiting
- Manager persistence
- Job interface compliance

### metrics/
- Cost calculation
- Recording patterns

### pipeline/
- Stage interface
- Registry patterns
- Prompt organization

### providers/
- Client implementations
- Rate limiter
- Retry logic

### schema/
- GraphQL schema organization
- Registry patterns

### server/
- Lifecycle management
- Endpoint registration
- Middleware chain

### svcctx/
- Extractor completeness
- Context key patterns

### testutil/
- Mock implementations
- Test helpers

## Output

Package report:
- Files reviewed
- Issues found (by category)
- Fixes applied
- Recommendations
