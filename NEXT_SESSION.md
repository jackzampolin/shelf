# Next Session: Correction Stage Analysis

## Objective
Review correction stage outputs from the re-runs with improved prompts to verify hyphen removal quality.

## Books to Analyze
1. **accidental-president** (255 pages)
2. **right-wing-critics** (unknown page count)

## Tasks

### 1. Run Correction Analysis
Use the existing analysis script to check correction quality:

```bash
# Analyze accidental-president
uv run python tools/analyze_correction.py accidental-president

# Analyze right-wing-critics
uv run python tools/analyze_correction.py right-wing-critics
```

### 2. Key Metrics to Check

**Primary Goal: Verify hyphen removal**
- Look for examples of line-break hyphens in the analysis output
- Check if hyphens are **fully removed** (both hyphen + space)
- Compare to previous run where we saw "cam-paign" instead of "campaign"

**Expected Improvements:**
- Line-break hyphens should be: "cam- paign" → "campaign" ✅
- NOT: "cam- paign" → "cam-paign" ❌

**Other Quality Checks:**
- Corrections applied rate (should be >80%)
- Contradictory "No OCR errors" cases (should be minimal)
- Average confidence scores
- Cost per page

### 3. Spot Check Pages

Pick 3-5 random pages from each book and manually verify:
- Read both OCR and corrected JSON files
- Confirm line-break hyphens are fully removed
- Check that real compound hyphens are preserved ("Vice-President", "self-aware")

**Example pages to check:**
```bash
# For accidental-president, check page 25 (we saw issues here before)
cat ~/Documents/book_scans/accidental-president/ocr/page_0025.json | jq '.blocks[].paragraphs[].text' | grep -E '\w+- \w+'
cat ~/Documents/book_scans/accidental-president/corrected/page_0025.json | jq '.blocks[].paragraphs[] | select(.text != null) | .text' | grep -E '\w+-\w+'
```

If you see words like "cam-paign" or "Kan-sas" in corrected output, the prompt fix didn't work.

### 4. Check for Failures

Review any failed pages from the analysis:
```bash
# Get failed page count from checkpoint
jq -r '.status, .total_pages, (.completed_pages | length)' ~/Documents/book_scans/accidental-president/checkpoints/correction.json
```

If there are failures:
- Check logs to identify error patterns
- Categorize: API errors vs content issues
- Determine if retry would help

### 5. Generate Summary Report

Create a brief summary:
- Total pages processed per book
- Hyphen removal quality (A/B/C grade)
- Cost per page
- Failure rate and causes
- Recommendation: Accept quality or need prompt iteration

## Context from This Session

**Prompt Changes Made:**
1. Added explicit "remove BOTH hyphen + space" instruction
2. Added wrong vs correct examples with ❌/✅
3. Updated pattern description: `[word]- [space][word] → join into single word`
4. Fixed 0-based indexing schema issue (minimum: 1 in JSON schema)

**Previous Quality (before prompt fix):**
- accidental-president: B- quality
- 80.5% corrections applied
- 19.5% had remnant hyphens ("cam-paign" artifacts)
- $0.0008/page cost

**Expected Quality (after prompt fix):**
- A/A- quality
- 90%+ corrections applied correctly
- Minimal hyphen artifacts
- Similar cost per page

## Success Criteria

✅ **Success**:
- No "cam-paign" style artifacts in spot checks
- Corrections applied rate >85%
- Real compound hyphens preserved
- Cost stays under $0.001/page

⚠️ **Needs Work**:
- Still seeing hyphen artifacts
- Corrections applied rate <80%
- Many "contradictory no errors" cases

## Files Modified This Session
- `pipeline/2_correction/__init__.py` - Prompt improvements, --no-retry flag, max_retries param
- `ar.py` - Added --no-retry CLI flag
- `infra/llm_client.py` - (Will reduce backoff delays before commit)
- `tools/analyze_correction.py` - Analysis script (already exists)

## Reference

Previous analysis showed page 25 had issues:
```
OCR: "cam- paign, Kan- sas, peni- tentiary"
Old correction: "cam-paign, Kan-sas, peni-tentiary" ❌
Expected: "campaign, Kansas, penitentiary" ✅
```

Verify this is now fixed in the new run.
