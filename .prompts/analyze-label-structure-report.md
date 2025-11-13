# Label-Structure Report Analysis Prompt

You are analyzing the label-structure stage output for a book scan. Your task is to provide a comprehensive analysis of page number detection quality and identify patterns in failed detections.

## Input Files

**Primary source:**
- `label-structure/report.csv` - Page-by-page detection results

**Supporting data:**
- `label-structure/page_{:04d}.json` - Individual page metadata
- `source/page_{:04d}.png` - Original page images (if needed)

## Analysis Tasks

### 1. Overall Statistics

From `report.csv`, calculate:
- Total pages
- Pages with `sequence_status = "ok"` (correctly detected)
- Pages with `page_num_present = False` (no page number detected)
- Pages with `needs_review = True` (flagged for manual review)
- Distribution of sequence_status types (gap_1, gap_2, backward_jump, type_change, etc.)

### 2. Gap Analysis

Identify all gap patterns:
- Count by gap size (gap_1, gap_2, gap_3, gap_4+)
- List scan pages with gaps
- For each gap type, provide:
  - Scan page ranges
  - Previous/next detected page numbers
  - Context from headings (if available)
  - Likely cause (chapter boundary, illustration, OCR failure, etc.)

### 3. Needs Review Cases

For each page with `needs_review = True`:
- Scan page number
- Sequence status (backward_jump, large gap, etc.)
- Detected value vs expected value
- Header/footer text (if present)
- Headings text (if present)
- Hypothesis: Why does this page need review?

**Special focus on:**
- **Backward jumps**: Are these chapter title pages? Does the detected number match a heading?
- **Type changes**: Are these legitimate roman ↔ arabic transitions at section boundaries?
- **Large gaps**: Are there missing pages or just unnumbered sections?

### 4. Pattern Identification

Look for systematic issues:
- Do backward_jumps cluster at specific intervals? (e.g., every ~20 pages = chapters)
- Do gaps occur at predictable locations? (front matter, part dividers, back matter)
- Are there specific page ranges with poor detection? (damaged scans, poor quality)
- Do headings provide clues about what the page should be numbered?

### 5. Healing Recommendations

Based on your analysis, recommend:
- **Trivially healable**: Cases where the correct page number is obvious from context
- **Requires LLM vision**: Cases needing image examination
- **Requires manual review**: Complex cases where human judgment needed
- **Leave as-is**: Intentionally unnumbered pages (blank pages, dividers, etc.)

## Output Format

Generate a markdown report named `label-structure/analysis.md` with this structure:

```markdown
# Label-Structure Analysis Report

**Book:** [Scan ID from directory name]
**Date:** [Current date]
**Total Pages:** [N]

## Executive Summary

[2-3 sentences summarizing overall quality and key findings]

## Statistics

| Metric | Count | Percentage |
|--------|-------|------------|
| Total pages | X | 100% |
| Correctly sequenced | X | X% |
| Missing page numbers | X | X% |
| Needs review | X | X% |
| Gaps (any size) | X | X% |

## Gap Distribution

| Gap Type | Count | Scan Pages (first 10) |
|----------|-------|----------------------|
| gap_1 | X | [list] |
| gap_2 | X | [list] |
| ... | ... | ... |

## Needs Review Analysis

### Backward Jumps (N cases)

[For each backward jump, provide:]
- **Scan Page X**: Detected `Y`, expected `Z` (gap: -N)
  - Headings: [heading text if present]
  - Hypothesis: [Chapter title page showing chapter number instead of page number]

### Type Changes (N cases)

[Analysis of roman ↔ arabic transitions]

### Large Gaps (gap_4+) (N cases)

[Analysis of multi-page gaps]

## Patterns Identified

1. **[Pattern Name]**: [Description]
   - Affected pages: [list]
   - Likely cause: [explanation]
   - Recommendation: [action]

2. ...

## Healing Recommendations

### Auto-Healable (N pages)

[List pages that can be healed with simple logic]

### Vision Review Needed (N pages)

[List pages requiring LLM vision analysis]
- Scan page X: [reason why vision needed]

### Manual Review Needed (N pages)

[List pages requiring human judgment]

### No Action Needed (N pages)

[List intentionally unnumbered pages]

## Quality Assessment

**Overall Grade:** [A/B/C/D/F]
- A: >95% correct sequence, <5 needs_review
- B: 85-95% correct, <20 needs_review
- C: 70-85% correct, <50 needs_review
- D: 50-70% correct, significant issues
- F: <50% correct, major systematic problems

**Key Issues:**
- [Issue 1]
- [Issue 2]

**Strengths:**
- [Strength 1]
- [Strength 2]

## Next Steps

1. [Specific action item based on findings]
2. [Another action item]
```

## Important Notes

- Focus on **actionable insights**, not just statistics
- Provide **specific scan page numbers** for all findings
- Make **concrete recommendations** for each issue type
- **Explain your reasoning** for each hypothesis
- If you need to examine actual page images to understand an issue, note that clearly

Generate the report now.
