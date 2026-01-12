# Quick Codebase Audit

Fast audit focusing on the most common issues. Use `/audit-full` for comprehensive review.

## Instructions

1. Create a short TodoWrite list
2. Check each area quickly
3. Report findings without deep diving
4. Fix obvious issues, flag others for `/audit-full`

## Quick Checks

### 1. File Size Scan
```bash
find internal/ -name "*.go" -exec wc -l {} + | sort -rn | head -20
```
Flag any files >400 lines.

### 2. TODO/FIXME Comments
```bash
grep -rn "TODO\|FIXME" internal/ --include="*.go"
```
These should be in GitHub issues, not code (ADR 001).

### 3. Constructor Injection Check
Look for patterns that should use svcctx:
```go
// Bad: constructor injection
func NewHandler(jm *jobs.Manager) *Handler

// Good: context extraction
jm := svcctx.JobManagerFrom(ctx)
```

### 4. Direct File Writes
Check for filesystem state (should be DefraDB):
```bash
grep -rn "os.WriteFile\|os.Create\|ioutil.WriteFile" internal/
```

### 5. Missing Metrics
Check LLM/OCR calls record metrics:
```bash
grep -rn "\.Chat(\|\.OCR(" internal/ --include="*.go"
```
Each should have corresponding metric recording nearby.

### 6. Naming Convention Violations
- Stage names should be `hyphen-case`
- Go exports should be `PascalCase`
- Files should be `snake_case.go`

## Output

Quick summary:
- Critical issues (fix now)
- Warnings (fix in /audit-full)
- Clean areas (no issues)
