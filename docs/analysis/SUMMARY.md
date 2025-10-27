# Corrected Stage Analysis Summary

## Files Generated

1. **corrected_stage_visualization_guide.md** - Comprehensive analysis (29 KB, 10 sections)
   - Complete data structure reference
   - Quality metric interpretation
   - 7 recommended visualizations with mockups
   - Before/after comparison strategy
   - Implementation priorities

## Quick Reference

### Report Schema Columns (report.csv)
```
page_num | total_corrections | avg_confidence | text_similarity_ratio | characters_changed
```

### Key Quality Metrics

| Metric | Priority | Green Zone | Yellow Zone | Red Zone |
|--------|----------|-----------|-------------|----------|
| text_similarity_ratio | ⭐⭐⭐ (most important) | 0.95-1.0 | 0.85-0.95 | <0.85 |
| avg_confidence | ⭐⭐ | >0.90 | 0.85-0.90 | <0.85 |
| total_corrections (%) | ⭐⭐ | 1-15% | 15-30% | >40% |
| characters_changed | ⭐ (complement to similarity) | Low with high similarity | High with high similarity | High with low similarity |

### Essential Visualizations (P0 Priority)

1. **Stat Cards** - Overview metrics
   - Pages processed, total corrections, avg confidence, avg similarity, cost
   - Build first - foundation for dashboard

2. **Confidence Histogram** - Distribution of correction confidence
   - Identifies low-confidence pages needing review
   - Watch for >85% pages with 0.95+ (over-confidence)

3. **Similarity Histogram** - Distribution of text similarity
   - Primary quality metric
   - Red flag if significant pages <0.85 (over-correction)

4. **Problem Pages Table** - Prioritized review list
   - Sortable/filterable
   - Shows similarity, confidence, correction volume
   - Most actionable visualization

5. **Before/After Text Comparison** - Per-page diff view
   - Side-by-side OCR vs corrected text
   - Shows actual changes in context
   - Enables spot-checking

### Data Access Patterns

**Report CSV:**
```python
import pandas as pd
report = pd.read_csv('corrected/report.csv')
# Columns: page_num, total_corrections, avg_confidence, text_similarity_ratio, characters_changed
```

**Page Output:**
```python
import json
with open('corrected/page_0042.json') as f:
    page = json.load(f)
# Structure: blocks[block_num].paragraphs[par_num].{text, notes, confidence}
```

**Checkpoint Metrics:**
```python
from infra.storage.checkpoint import CheckpointManager
checkpoint = CheckpointManager('corrected', storage)
all_metrics = checkpoint.get_all_metrics()  # Dict[page_num, metrics_dict]
```

### Implementation Road Map

**Phase 1 (P0 - Essential):**
- Stat cards (UI card component)
- Confidence histogram (bar chart)
- Similarity histogram (bar chart)
- Problem pages table (sortable data table)
- Cost tracking card

**Phase 2 (P1 - High Value):**
- Scatter plot (correction volume vs quality)
- Before/after text diff viewer
- Page image + corrections overlay

**Phase 3 (P2 - Nice to Have):**
- Cost-quality trade-off analysis chart
- Model performance comparison
- Distribution statistical tests

## Architecture Notes

### Sparse Design
Correction stage outputs **sparse corrections only** - only blocks/paragraphs with changes are stored. Need to reconstruct full corrected text by merging OCR + corrections for comparison views.

### Schema Enforcement
Per-page JSON schemas prevent LLM from hallucinating new structure (can't add/remove blocks or paragraphs - enforced by `build_page_specific_schema()`).

### Before/After Reconstruction Algorithm
```python
def reconstruct_corrected_text(ocr_page, corrections):
    result = {}
    for block_idx, block in enumerate(ocr_page['blocks']):
        for para_idx, para in enumerate(block['paragraphs']):
            corr_block = corrections['blocks'][block_idx]
            corr_para = corr_block['paragraphs'][para_idx]
            
            # Use corrected text if available, else OCR text
            if corr_para.get('text') is not None:
                result[f"b{block_idx}_p{para_idx}"] = corr_para['text']
            else:
                result[f"b{block_idx}_p{para_idx}"] = para['text']
    return result
```

## Quality Interpretation

### Over-Correction Red Flags
- Low similarity (< 0.85) with high corrections = rewrote too much
- High confidence (>0.95) on low similarity pages = over-confident LLM
- Similarity dips suddenly on one page = anomaly, needs review

### Under-Correction Indicators
- High corrections (>30%) with high similarity (>0.98) = only minor fixes made
- Many corrections but confidence <0.90 = uncertain fixes

### Ideal Distribution
- 0.95-1.0 similarity: 60-70% of pages (very minor fixes)
- 0.90-0.95 similarity: 25-35% of pages (normal corrections)
- 0.85-0.90 similarity: <5% of pages (concerning)
- <0.85 similarity: <2% of pages (red flag)

Avg confidence around 0.90-0.95 is healthy (not overconfident).

## Cost Optimization Insights

Looking at `checkpoint[cost_usd]` + `checkpoint[tokens_total]`:
- Vision downsampling reduces token usage 50% (saves money)
- Rate limiting @ 100 req/min prevents API overload
- Batch processing amortizes queue time
- Full book (~400 pages) typically costs $1-4

## Next Steps for Implementation

1. Create viewer UI component scaffold
2. Implement report.csv loading and aggregation
3. Build stat card component
4. Implement histogram charts (confidence, similarity)
5. Build problem pages table with sorting/filtering
6. Implement before/after diff viewer using OCR + corrections files
7. Add scatter plot for correlation analysis
8. Integrate with main viewer navigation

## References

- Correction stage code: `pipeline/correction/__init__.py`
- Schemas: `pipeline/correction/schemas.py`
- README: `pipeline/correction/README.md`
- Report generation: `infra/pipeline/base_stage.py:151-246`
