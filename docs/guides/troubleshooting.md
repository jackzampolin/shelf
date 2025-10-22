# Troubleshooting Guide

## Stage Failures and Recovery

### Stage Won't Start

**Symptom:** before() hook fails with FileNotFoundError

**Cause:** Missing dependency outputs or incomplete upstream stage

**Solution:**
```bash
# Check dependency status
uv run python shelf.py status <scan-id>

# Run missing upstream stage
uv run python shelf.py process <scan-id> --stage <dependency-name>
```

**Prevention:** Always run stages in order: ocr → corrected → labels → merged

### Stage Fails Mid-Processing

**Symptom:** Exception during run(), some pages completed

**Recovery:**
```bash
# Resume from checkpoint (automatic)
uv run python shelf.py process <scan-id> --stage <stage-name>
```

Checkpoint tracks completed pages - only remaining pages reprocessed. No duplicate work or wasted cost.

**Check progress:**
```bash
# View checkpoint status
jq '.status, .progress' ~/Documents/book_scans/<scan-id>/<stage>/.checkpoint
```

### Want to Start Fresh

**Symptom:** Stage completed but results unsatisfactory

**Solution:**
```bash
# Reset stage (prompts for confirmation)
uv run python shelf.py clean <scan-id> --stage <stage-name>

# Skip confirmation
uv run python shelf.py clean <scan-id> --stage <stage-name> -y
```

**Warning:** Deletes `.checkpoint` but preserves output files. Re-running will overwrite.

## Checkpoint Issues

### Checkpoint Corrupted

**Symptom:** JSON parse error when loading checkpoint

**Recovery:**
Checkpoint automatically rebuilds from valid output files:
1. Scans stage output directory
2. Validates each `page_*.json` file
3. Marks valid files as complete
4. Resumes from actual state

**Manual rebuild:**
```bash
# Delete corrupt checkpoint
rm ~/Documents/book_scans/<scan-id>/<stage>/.checkpoint

# Re-run stage (will scan outputs and resume)
uv run python shelf.py process <scan-id> --stage <stage-name>
```

### Checkpoint Says Complete, Files Missing

**Cause:** Files deleted manually or output validation fails

**Behavior:** `scan_existing_outputs()` removes missing pages from checkpoint → marks incomplete → re-processes

**Verify:**
```bash
# Count outputs vs checkpoint
ls ~/Documents/book_scans/<scan-id>/<stage>/page_*.json | wc -l
jq '.page_metrics | length' ~/Documents/book_scans/<scan-id>/<stage>/.checkpoint
```

## Schema Validation Errors

### Output Schema Mismatch

**Symptom:** ValidationError when saving page

**Cause:** Stage producing data that doesn't match output_schema

**Debug:**
```python
# Check what stage is producing
print(json.dumps(data, indent=2))

# Compare to schema
print(MyOutputSchema.model_json_schema())
```

**Common issues:**
- Missing required fields
- Wrong types (str vs int)
- Invalid enum values
- Nested structure mismatch

### Input Schema Mismatch

**Symptom:** ValidationError when loading dependency page

**Cause:** Upstream stage schema changed or corrupted output

**Debug:**
```bash
# Validate upstream output manually
python -c "
from pipeline.ocr.schemas import OCRPageOutput
import json
data = json.load(open('ocr/page_0001.json'))
OCRPageOutput(**data)
"
```

**Fix:** Re-run upstream stage or update input_schema to match.

## LLM-Related Issues

### Rate Limiting

**Symptom:** Many requests queued, slow progress

**Cause:** OpenRouter rate limits (100 req/min default)

**Solution:**
1. Reduce workers: `--workers 20` (default 30)
2. Check OpenRouter dashboard for actual limits
3. Add rate_limit parameter to LLMBatchClient

### High Costs

**Symptom:** Checkpoint shows unexpectedly high cost_usd

**Analysis:**
```bash
# Check cost per page
jq '.page_metrics | to_entries | .[] | .value.cost_usd' .checkpoint | \
  awk '{sum+=$1; count++} END {print "Avg:", sum/count, "Total:", sum}'
```

**Optimizations:**
1. **Image downsampling:** Reduce from 300 DPI to 200 DPI
2. **Faster model:** Switch from gpt-4o to gpt-4o-mini
3. **Batch size:** Increase workers (amortizes queue time)

**See:** Stage-specific cost guidance in stage READMEs

### Low Quality Corrections

**Symptom:** Low text_similarity_ratio or high corrections but poor results

**Diagnosis:**
```bash
# Check report for outliers
sort -t, -k3 -n corrected/report.csv | head -20  # Lowest similarity
sort -t, -k2 -n corrected/report.csv | tail -20  # Most corrections
```

**Causes:**
- Hallucinations (LLM inventing text)
- Poor OCR quality (garbage in, garbage out)
- Wrong model for content type

**Solutions:**
1. Manual review flagged pages
2. Try different model (Claude vs GPT)
3. Improve OCR quality (better source images)

## Thread Safety Issues

### Race Conditions

**Symptom:** Checkpoint inconsistent with outputs, random failures

**Unlikely:** Storage and checkpoint use proper locking

**Debug:**
```python
# Check for lock contentions in logs
grep "waiting for lock" logs/<stage>_*.jsonl
```

**If persistent:** Report as bug - should not happen with current design.

## Performance Problems

### Slow Processing

**CPU stages (OCR):**
- Check worker count: Should match `cpu_count()`
- Monitor CPU usage: Should be near 100%
- Check I/O: SSD vs HDD makes 5-10x difference

**LLM stages (Correction, Label):**
- Check queue time in logs: >5s indicates rate limiting
- Monitor workers: All should be active
- Check network latency to OpenRouter

**Merge stage:**
- Check I/O: Reading 3 files per page
- Increase workers if SSD (default 8 → 16)

### Memory Issues

**Symptom:** OOM errors, system swapping

**Cause:** Too many workers for available RAM

**Solution:**
```bash
# Reduce workers
uv run python shelf.py process <scan-id> --workers 10
```

**Memory per worker:**
- OCR: ~50MB (Tesseract + page image)
- Correction: ~100MB (LLM batch + images)
- Label: ~100MB (similar to correction)
- Merge: ~20MB (JSON files only)

## Common Patterns

### Resume After Crash

Always safe to re-run same command:
```bash
uv run python shelf.py process <scan-id> --stage <stage-name>
```

Checkpoint ensures no duplicate work. Cost only for incomplete pages.

### Verify Stage Completion

```bash
# Check status
uv run python shelf.py status <scan-id>

# Or directly
jq '.status' ~/Documents/book_scans/<scan-id>/<stage>/.checkpoint
```

Status values: `in_progress`, `completed`, `failed`

### Inspect Page Outputs

```bash
# Pretty print JSON
jq '.' ~/Documents/book_scans/<scan-id>/<stage>/page_0050.json

# Extract specific field
jq '.blocks[].text' <stage>/page_0050.json
```

### Check Logs for Errors

```bash
# Find errors in logs
grep '"level":"ERROR"' logs/<stage>_*.jsonl | jq '.'

# Page-specific errors
grep '"page":42' logs/<stage>_*.jsonl | grep ERROR
```

## When to File a Bug

File issue if:
- Checkpoint corruption despite atomic writes
- Schema validation errors with valid data
- Thread safety violations
- Stage fails repeatedly with same error
- Checkpoint and filesystem out of sync

**Include:**
- Stage name and command used
- Checkpoint status (`.checkpoint` file)
- Relevant log entries
- Sample output files (if schema-related)

See: https://github.com/jackzampolin/scanshelf/issues
