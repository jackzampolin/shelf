# Corrected Stage Analysis & Visualization Guide

This directory contains comprehensive analysis of the Correction stage data structures and visualization recommendations for a corrected stage viewer.

## Files in This Analysis

### 1. **SUMMARY.md** (Quick Reference)
Start here for a 5-minute overview.
- Key metrics and quality zones
- Essential visualizations (P0 priority)
- Data access patterns with code examples
- Implementation roadmap
- Architecture notes

### 2. **corrected_stage_visualization_guide.md** (Comprehensive Guide)
Full 29 KB analysis with deep dives.
- Report schema structure
- Page output schema (sparse corrections design)
- Checkpoint metrics reference
- Quality interpretation guidelines
- 7 recommended visualizations with ASCII mockups
- Before/after comparison strategy
- Data files reference (report.csv, page_*.json, .checkpoint)
- Recommended dashboard layout
- Quality interpretation guidelines

### 3. **viewer_mockup.txt** (Visual Design)
Detailed UI mockups showing layout and interaction.
- Full-page corrected stage dashboard
- Detail view for problem page analysis
- Color scheme and styling
- Component reference
- User interaction flow

## Quick Navigation

**Starting a new viewer implementation?**
1. Read SUMMARY.md (overview + priorities)
2. Skim corrected_stage_visualization_guide.md (Section 5: Visualizations)
3. Reference viewer_mockup.txt for UI layout
4. Implement Phase 1 components (see SUMMARY.md roadmap)

**Understanding quality metrics?**
- See SUMMARY.md "Key Quality Metrics" table
- See corrected_stage_visualization_guide.md Section 4 "Data Quality Indicators"
- See corrected_stage_visualization_guide.md Section 9 "Key Insights"

**Building before/after comparison?**
- See corrected_stage_visualization_guide.md Section 6 "Comparison Strategy"
- Reference SUMMARY.md "Before/After Reconstruction Algorithm"
- Check viewer_mockup.txt "Detail View" for UI example

**Need implementation details?**
- See corrected_stage_visualization_guide.md Section 7 "Data Files Reference"
- Check SUMMARY.md "Data Access Patterns" with code examples
- Reference correction stage code: `pipeline/correction/__init__.py`

## Key Insights

### The Correction Stage's Unique Challenge

Unlike OCR which produces full page text, Correction outputs **sparse corrections only** - only blocks/paragraphs that changed. This requires:
1. Loading both OCR (`ocr/page_*.json`) and corrected (`corrected/page_*.json`) files
2. Reconstructing full corrected text by merging them
3. Comparing side-by-side with diffs

### Most Important Quality Metric

**text_similarity_ratio** (primary indicator of over-correction)
- 0.95-1.0: Expected (minor fixes)
- 0.90-0.95: Normal (moderate corrections)
- 0.85-0.90: Concerning (major rewrites)
- <0.85: Red flag (possible hallucination)

### Why These Visualizations?

1. **Stat Cards** - Foundation (what's the overall state?)
2. **Histograms** - Identify problematic zones
3. **Scatter Plot** - Reveal correlation patterns (volume vs quality)
4. **Problem Pages Table** - Actionable list for manual review
5. **Before/After Viewer** - Verification tool for spot-checking

## Implementation Priorities

### Phase 1 (MVP - Essential for Usefulness)
- [ ] Stat cards component
- [ ] Report CSV loading
- [ ] Confidence histogram
- [ ] Similarity histogram
- [ ] Problem pages table with sorting
- [ ] Cost card

### Phase 2 (High Value - Core Functionality)
- [ ] Scatter plot (corrections vs quality)
- [ ] Before/after text diff viewer
- [ ] Page navigation in detail view

### Phase 3 (Nice to Have - Polish)
- [ ] Cost-quality trade-off analysis
- [ ] Model comparison charts
- [ ] Statistical tests
- [ ] Export functionality

## Code References

### Data Loading Examples

**Report CSV:**
```python
import pandas as pd
from pathlib import Path

report_path = Path("corrected/report.csv")
if report_path.exists():
    report_df = pd.read_csv(report_path)
    # Columns: page_num, total_corrections, avg_confidence, text_similarity_ratio, characters_changed
    
    # Aggregate metrics
    print(f"Avg Confidence: {report_df['avg_confidence'].mean():.3f}")
    print(f"Avg Similarity: {report_df['text_similarity_ratio'].mean():.3f}")
    
    # Find problematic pages
    problems = report_df[report_df['text_similarity_ratio'] < 0.85]
```

**Page Output (Sparse Corrections):**
```python
import json

with open('corrected/page_0042.json') as f:
    page = json.load(f)

# Access corrections
for block in page['blocks']:
    block_num = block['block_num']
    for para in block['paragraphs']:
        par_num = para['par_num']
        if para.get('text'):  # Only if text was changed
            print(f"Block {block_num}, Para {par_num}:")
            print(f"  Confidence: {para['confidence']}")
            print(f"  Notes: {para.get('notes', 'N/A')}")
```

**Checkpoint Metrics:**
```python
from infra.storage.checkpoint import CheckpointManager
from infra.storage.book_storage import BookStorage

storage = BookStorage('accidental-president')
checkpoint = CheckpointManager('corrected', storage)

# Get all metrics
all_metrics = checkpoint.get_all_metrics()
# Dict[page_num, {page_num, cost_usd, total_corrections, avg_confidence, text_similarity_ratio, ...}]

# Process for visualization
for page_num, metrics in all_metrics.items():
    print(f"Page {page_num}: {metrics['text_similarity_ratio']:.3f} similarity")
```

## Quality Interpretation Cheat Sheet

### Red Flags (Needs Manual Review)
- Similarity < 0.85: Model rewrote too much
- Confidence < 0.85: Model uncertain about changes
- Corrections > 40%: Exceptionally high edit rate
- Confidence HIGH (>0.95) but Similarity LOW (<0.85): Overconfident model

### Healthy Indicators
- 60-70% pages with 0.95-1.0 similarity
- 25-35% pages with 0.90-0.95 similarity
- <5% pages with 0.85-0.90 similarity
- <2% pages with <0.85 similarity
- Avg confidence around 0.90-0.95 (not over-confident)

### Cost Optimization
- Vision downsampling reduces token usage 50%
- Full 400-page book typically costs $1-4
- Rate limiting @ 100 req/min prevents overload
- High cost + low quality = prioritize for review/rerun with different model

## Architecture Decisions

### Why Sparse Corrections?
- Reduces storage overhead (only changed text)
- Preserves OCR block/paragraph structure
- Per-page schemas prevent LLM hallucination
- Enables efficient merge stage later

### Why Multiple Metrics?
- **Similarity**: Magnitude of change (most important)
- **Confidence**: Model's self-assessment
- **Correction count**: Volume of changes
- **Characters changed**: Granular edit distance

### Report Schema vs Checkpoint Schema
- **Checkpoint**: Full metrics (timing, tokens, cost, LLM details)
- **Report**: Quality only (excludes performance metrics)
- BaseStage automatically generates report.csv from checkpoint metrics

## Troubleshooting

**Problem: No report.csv found**
→ Check if correction stage has completed
→ Check `checkpoint/.checkpoint` file status
→ Verify stage name is 'corrected' (not 'correction')

**Problem: Metrics don't match expectations**
→ Check model_used in checkpoint (gpt-4o vs gpt-4-turbo have different costs)
→ Verify OCR quality first (high OCR errors → expected high correction rates)
→ Check if same book was corrected with different settings

**Problem: Sparse corrections look incomplete**
→ Verify correction response_schema matches OCR structure
→ Check for failed pages in checkpoint
→ Compare OCR blocks count with corrected blocks count (should match exactly)

## Next Steps

1. **Understand the data**: Read SUMMARY.md + check actual report.csv
2. **Plan components**: Prioritize Phase 1 (stat cards + table + histograms)
3. **Start implementation**: Begin with stat card aggregations
4. **Add interactivity**: Implement table sorting/filtering
5. **Deep dive features**: Add before/after viewer and scatter plot
6. **Polish**: Add export, filtering, and help text

## Related Documentation

- `pipeline/correction/__init__.py` - Full correction stage implementation
- `pipeline/correction/schemas.py` - Schema definitions
- `pipeline/correction/README.md` - Correction stage design doc
- `infra/pipeline/base_stage.py` - Report generation code (lines 151-246)
- `infra/pipeline/schemas.py` - Base metric schemas
