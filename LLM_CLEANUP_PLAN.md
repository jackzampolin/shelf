# LLM Text Cleanup Pipeline - Detailed Implementation Plan

## Overview

Three-agent per-page processing with 3-page context windows for OCR error detection, correction, and verification.

## Architecture

### Processing Unit: Single Page with Context
- **Input:** 3 consecutive pages (N-1, N, N+1)
- **Output:** Cleaned page N only
- **Context:** Adjacent pages provide sentence continuity for cross-page errors

### Three-Agent Pipeline

```
┌─────────────┐
│   Page N-1  │ ─┐
├─────────────┤  │
│   Page N    │ ─┼──> Agent 1: Detect errors on Page N only
├─────────────┤  │    Output: error_catalog.json
│   Page N+1  │ ─┘
└─────────────┘
                          │
                          ▼
┌─────────────┐    ┌─────────────┐
│   Page N    │ ──>│  Agent 2:   │
│  (original) │    │  Fix errors │
└─────────────┘    │  using      │
                   │  catalog    │
┌─────────────┐    └─────────────┘
│ Error       │ ──>       │
│ Catalog     │           │
└─────────────┘           ▼
                   ┌─────────────┐
                   │  Corrected  │
                   │   Page N    │
                   └─────────────┘
                          │
                          ▼
┌──────────────────┐  ┌─────────────┐
│  Original        │─>│  Agent 3:   │
│  Page N          │  │  Verify     │
├──────────────────┤  │  corrections│
│  Error Catalog   │─>│             │
├──────────────────┤  └─────────────┘
│  Corrected       │─>       │
│  Page N          │         │
└──────────────────┘         ▼
                      ┌─────────────┐
                      │ Verification│
                      │   Report    │
                      │  + Quality  │
                      │    Score    │
                      └─────────────┘
```

## Filesystem Structure

```
~/Documents/book_scans/The-Accidental-President/
│
├── batches/                    # Original scanned PDFs
│   └── batch_001/
│       └── The-Accidental-President_p0001-0077.pdf
│
├── raw_pdfs/                   # Archive copies
│
├── ocr_text/                   # ✅ COMPLETE - Raw Tesseract output
│   ├── batch_001/
│   │   ├── page_0001.txt      # Input for pipeline
│   │   ├── page_0002.txt
│   │   └── ...
│   └── batch_005/
│
├── llm_agent1_errors/          # Agent 1: Error detection (JSON)
│   ├── page_0001.json
│   ├── page_0002.json
│   └── ...
│
├── llm_agent2_corrected/       # Agent 2: Corrected text
│   ├── page_0001.txt
│   ├── page_0002.txt
│   └── ...
│
├── llm_agent3_verification/    # Agent 3: Verification reports (JSON)
│   ├── page_0001.json
│   ├── page_0002.json
│   └── ...
│
├── needs_review/               # Pages flagged for human review
│   └── page_0042.json          # Low confidence or issues detected
│
├── final_text/                 # Final merged output
│   └── The-Accidental-President_complete.txt
│
└── metadata.json               # Updated with LLM processing status
```

## Agent 1: Error Detection

### Purpose
Identify OCR errors without fixing them. Output structured error catalog.

### Input
- 3 pages of text (N-1, N, N+1)
- Page number N to analyze

### Prompt Template

```python
AGENT1_SYSTEM_PROMPT = """You are an OCR error detection specialist. Your job is to identify potential OCR errors in scanned book text.

RULES:
1. DO NOT fix or correct anything
2. ONLY identify and catalog potential errors
3. Focus ONLY on the specified target page
4. Use adjacent pages for context but don't report errors from them
5. Report errors with high confidence (>0.7) only

ERROR TYPES TO DETECT:
- Character substitutions (rn→m, l→1, O→0)
- Spacing errors (word run-together, extra spaces)
- Hyphenated line breaks that should be joined
- OCR artifacts (|||, ___, etc.)
- Obvious typos from OCR confusion

OUTPUT FORMAT:
Return valid JSON only, no additional text:
{
  "page_number": N,
  "total_errors_found": X,
  "errors": [
    {
      "error_id": 1,
      "location": "line 5, position 10-15",
      "original_text": "tbe",
      "error_type": "character_substitution",
      "confidence": 0.95,
      "suggested_correction": "the",
      "context_before": "walked into ",
      "context_after": " room and"
    }
  ]
}"""

AGENT1_USER_PROMPT = """Analyze PAGE {page_num} ONLY for OCR errors.

Use pages {page_num-1} and {page_num+1} for context, but ONLY report errors from page {page_num}.

PAGE {page_num-1} (context only):
{prev_page_text}

PAGE {page_num} (TARGET - analyze this page):
{current_page_text}

PAGE {page_num+1} (context only):
{next_page_text}

Return JSON error catalog for page {page_num} only."""
```

### Output Format

```json
{
  "page_number": 42,
  "processing_timestamp": "2025-09-29T12:00:00",
  "total_errors_found": 5,
  "errors": [
    {
      "error_id": 1,
      "location": "line 7, position 15-18",
      "original_text": "tbe",
      "error_type": "character_substitution",
      "confidence": 0.95,
      "suggested_correction": "the",
      "context_before": "walked into ",
      "context_after": " room and"
    },
    {
      "error_id": 2,
      "location": "line 12, position 42-48",
      "original_text": "presi-\ndent",
      "error_type": "hyphenated_linebreak",
      "confidence": 0.92,
      "suggested_correction": "president",
      "context_before": "the ",
      "context_after": " walked"
    }
  ],
  "agent_metadata": {
    "model": "claude-3.5-sonnet",
    "temperature": 0.1,
    "tokens_used": 2400
  }
}
```

### Special Cases
- **Page 1:** No previous page, use pages 1-2 only
- **Page 447:** No next page, use pages 446-447 only
- **Empty/title pages:** May have 0 errors, still process for consistency

## Agent 2: Correction Application

### Purpose
Apply ONLY the corrections specified in Agent 1's error catalog. Do not make any other changes.

### Input
- Original page N text
- Error catalog from Agent 1

### Prompt Template

```python
AGENT2_SYSTEM_PROMPT = """You are an OCR correction specialist. Apply ONLY the specific corrections provided in the error catalog.

RULES:
1. Apply ONLY the corrections listed in the error catalog
2. Do NOT make any other changes, improvements, or "fixes"
3. Preserve all formatting, paragraph breaks, and structure
4. If a correction seems wrong, apply it anyway (verification will catch it)
5. Do NOT rephrase or modernize language
6. Mark each correction with [CORRECTED:id] inline for tracking

OUTPUT FORMAT:
Return the corrected text with inline correction markers."""

AGENT2_USER_PROMPT = """Apply these specific corrections to page {page_num}.

ERROR CATALOG:
{error_catalog_json}

ORIGINAL TEXT (Page {page_num}):
{original_text}

Return the corrected text with [CORRECTED:id] markers after each fix."""
```

### Output Format

```text
# Page 42
# Corrected by Agent 2
# Original errors: 5

Introduction / xi

The soldier[CORRECTED:1] walked across the[CORRECTED:2] field. He was thinking
about home. The president[CORRECTED:3] sat at his desk, contemplating the
enormous weight[CORRECTED:4] of his new responsibilities[CORRECTED:5].
```

### Correction Markers
- `[CORRECTED:1]` - Marks where correction 1 was applied
- Allows Agent 3 to verify each correction
- Will be removed in final merge

## Agent 3: Verification

### Purpose
Verify that Agent 2 applied corrections correctly and didn't make unauthorized changes.

### Input
- Original page N text
- Error catalog from Agent 1
- Corrected text from Agent 2

### Prompt Template

```python
AGENT3_SYSTEM_PROMPT = """You are a text verification specialist. Verify that corrections were applied correctly.

VERIFICATION CHECKLIST:
1. Were all identified errors corrected?
2. Were corrections applied accurately?
3. Were any unauthorized changes made?
4. Is document structure preserved?
5. Are there any new errors introduced?

CONFIDENCE SCORING:
- 1.0: Perfect, all corrections applied correctly
- 0.9: Minor issues, but acceptable
- 0.8: Some concerns, may need review
- <0.8: Significant issues, flag for human review

OUTPUT FORMAT:
Return valid JSON only."""

AGENT3_USER_PROMPT = """Verify corrections for page {page_num}.

ORIGINAL TEXT:
{original_text}

ERROR CATALOG (what should be fixed):
{error_catalog_json}

CORRECTED TEXT (what Agent 2 produced):
{corrected_text}

Verify each correction and check for unauthorized changes."""
```

### Output Format

```json
{
  "page_number": 42,
  "verification_timestamp": "2025-09-29T12:00:15",
  "all_corrections_applied": true,
  "corrections_verified": {
    "total_expected": 5,
    "correctly_applied": 5,
    "incorrectly_applied": 0,
    "missed": 0,
    "details": [
      {
        "error_id": 1,
        "expected": "tbe → the",
        "actual": "the",
        "status": "correct"
      }
    ]
  },
  "unauthorized_changes": [],
  "new_errors_introduced": [],
  "structure_preserved": true,
  "confidence_score": 0.98,
  "needs_human_review": false,
  "review_reason": null,
  "agent_metadata": {
    "model": "claude-3.5-sonnet",
    "temperature": 0,
    "tokens_used": 3200
  }
}
```

### Quality Thresholds

- **confidence_score >= 0.95:** Auto-approve, proceed to merge
- **0.80 <= confidence_score < 0.95:** Flag for spot-check review
- **confidence_score < 0.80:** Flag for full human review
- **unauthorized_changes > 0:** Always flag for review
- **new_errors_introduced > 0:** Always flag for review

## Processing Script Architecture

### Main Script: `book_llm_process.py`

```python
#!/usr/bin/env python3
"""
LLM Text Cleanup Pipeline
Processes OCR text through 3-agent validation
"""

class LLMBookProcessor:
    def __init__(self, book_title, model="claude-3.5-sonnet"):
        self.book_title = book_title
        self.model = model
        self.openrouter_api_key = os.getenv("OPENROUTER_API_KEY")

    def process_book(self):
        """Main entry point - process entire book"""
        # 1. Load metadata
        # 2. Get list of pages
        # 3. Process each page through 3 agents
        # 4. Track progress and costs
        # 5. Generate summary report

    def process_page(self, page_num):
        """Process single page through 3-agent pipeline"""
        # 1. Agent 1: Detect errors
        # 2. Agent 2: Apply corrections
        # 3. Agent 3: Verify corrections
        # 4. Save all outputs
        # 5. Return verification result

    def agent1_detect_errors(self, prev_page, current_page, next_page, page_num):
        """Agent 1: Error detection"""
        # Returns: error_catalog (JSON)

    def agent2_correct(self, original_text, error_catalog, page_num):
        """Agent 2: Apply corrections"""
        # Returns: corrected_text (string)

    def agent3_verify(self, original, corrected, error_catalog, page_num):
        """Agent 3: Verification"""
        # Returns: verification_report (JSON)

    def merge_pages(self):
        """Merge all verified pages into final text"""
        # 1. Load all verified pages in order
        # 2. Remove correction markers
        # 3. Remove page headers
        # 4. Concatenate
        # 5. Save to final_text/
```

## Cost & Time Estimates

### Per Page Costs (Claude 3.5 Sonnet via OpenRouter)

**Agent 1 (Detection):**
- Input: ~3K tokens (3 pages context)
- Output: ~500 tokens (JSON error catalog)
- Cost: $0.009 input + $0.0075 output = **$0.0165 per page**

**Agent 2 (Correction):**
- Input: ~1K tokens (page + error catalog)
- Output: ~1K tokens (corrected page)
- Cost: $0.003 input + $0.015 output = **$0.018 per page**

**Agent 3 (Verification):**
- Input: ~3K tokens (original + catalog + corrected)
- Output: ~800 tokens (verification report)
- Cost: $0.009 input + $0.012 output = **$0.021 per page**

**Total per page:** $0.0555 (~5.5 cents)

### Full Book (447 pages)

- Agent 1: 447 × $0.0165 = **$7.38**
- Agent 2: 447 × $0.018 = **$8.05**
- Agent 3: 447 × $0.021 = **$9.39**

**Total cost: ~$24.82**

### Processing Time

**Sequential:**
- ~3-5 seconds per page × 447 = ~22-37 minutes

**Parallel (10 concurrent requests):**
- 447 pages / 10 = 45 batches
- 45 × 5 seconds = ~4-8 minutes

**Recommendation:** Start sequential for first 10-20 pages to test, then parallelize.

## Implementation Phases

### Phase 1: Test Run (Pages 1-10)
**Goal:** Validate approach, tune prompts

1. Build `book_llm_process.py` core functionality
2. Process pages 1-10 sequentially
3. Review outputs:
   - Are error catalogs accurate?
   - Are corrections appropriate?
   - Are verifications catching issues?
4. Refine prompts based on results
5. Estimate final costs

**Success criteria:**
- All 3 agents produce valid output
- Verification confidence > 0.9 for most pages
- Corrections look accurate on manual review

### Phase 2: Full Book Processing
**Goal:** Process all 447 pages

1. Add parallelization (5-10 concurrent)
2. Add progress tracking and resume capability
3. Process all pages
4. Review flagged pages
5. Generate processing report

**Success criteria:**
- All pages processed
- <10% of pages flagged for review
- Final text is readable and accurate

### Phase 3: Merge and Finalize
**Goal:** Create final clean text

1. Merge all verified pages
2. Remove correction markers
3. Remove page headers
4. Handle any flagged pages
5. Generate final book text
6. Update metadata

**Success criteria:**
- Single clean text file
- Preserves all content
- No obvious errors remain

## Metadata Tracking

Add to `metadata.json`:

```json
{
  "llm_processing": {
    "status": "complete",
    "model_used": "claude-3.5-sonnet",
    "total_pages": 447,
    "processing_start": "2025-09-29T12:00:00",
    "processing_end": "2025-09-29T12:08:00",

    "agent1_errors": {
      "pages_processed": 447,
      "total_errors_found": 1247,
      "avg_errors_per_page": 2.79,
      "total_cost_usd": 7.38
    },

    "agent2_corrections": {
      "pages_processed": 447,
      "corrections_applied": 1243,
      "corrections_skipped": 4,
      "total_cost_usd": 8.05
    },

    "agent3_verification": {
      "pages_processed": 447,
      "high_confidence_pages": 425,
      "medium_confidence_pages": 18,
      "low_confidence_pages": 4,
      "avg_confidence_score": 0.96,
      "pages_needing_review": 4,
      "total_cost_usd": 9.39
    },

    "total_cost_usd": 24.82,
    "processing_time_seconds": 480,

    "quality_metrics": {
      "estimated_accuracy": 0.985,
      "human_review_required_count": 4,
      "human_review_pages": [42, 137, 289, 381]
    }
  }
}
```

## Error Handling

### API Failures
- Retry with exponential backoff (3 attempts)
- If page fails after 3 retries, flag for manual processing
- Continue with remaining pages

### Rate Limiting
- Implement rate limiting (10 requests/second max)
- Add delays between requests
- Track rate limit headers

### Invalid Outputs
- Validate JSON responses
- If Agent 1 returns invalid JSON, retry with stricter prompt
- If Agent 2 makes unauthorized changes, Agent 3 will catch it

### Resume Capability
- Track completed pages in metadata
- Can restart processing from last successful page
- Idempotent: reprocessing same page produces same output

## Quality Assurance

### Spot Checking
- Review 10 random pages manually
- Compare original vs corrected
- Verify no hallucinations or over-corrections

### Metrics to Track
- Errors found per page (should be 1-5 typically)
- Confidence scores (should average >0.9)
- Pages needing review (should be <10%)
- Processing cost per page
- Processing time per page

### Red Flags
- Confidence score suddenly drops
- Many pages flagged for review
- Unauthorized changes detected
- Processing errors increase

## Next Steps

1. **Create OpenRouter account** and get API key
2. **Build `book_llm_process.py`** with core functions
3. **Test on pages 1-10** and review outputs
4. **Refine prompts** based on test results
5. **Process full book** with parallelization
6. **Review flagged pages** and merge final text
7. **Update issue #24** and close with results

## Success Criteria

**This pipeline is successful if:**
- ✅ All 447 pages are processed
- ✅ <10% of pages need human review
- ✅ Final text is readable and accurate
- ✅ Total cost is <$30
- ✅ Processing completes in <30 minutes
- ✅ No hallucinations or major errors introduced
- ✅ Audit trail preserved for all changes

---

**Estimated completion:** 2-3 hours to build + test, 30 mins to process full book
**Estimated cost:** ~$25-30 for complete book processing
**Output:** Clean, verified text ready for database ingestion (Issue #27)