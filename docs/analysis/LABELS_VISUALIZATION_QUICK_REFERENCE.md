# Labels Stage Visualization - Quick Reference

## Data Structure Summary

### report.csv (Generated Automatically)
**Source**: `pipeline/label/__init__.py:generate_report()`
**Location**: `labels/report.csv`

```
Columns: page_num, printed_page_number, numbering_style, page_region,
         page_number_extracted, page_region_classified, total_blocks_classified,
         avg_classification_confidence, has_chapter_heading, has_section_heading,
         chapter_heading_text
```

### page_*.json (Full Classification Data)
**Location**: `labels/page_0001.json` through `labels/page_NNNN.json`

```json
{
  "page_number": int,
  "printed_page_number": str | null,
  "numbering_style": "roman" | "arabic" | "none" | null,
  "page_region": "front_matter" | "body" | "back_matter" | "toc_area" | null,
  "page_region_confidence": float [0.0-1.0],
  "blocks": [
    {
      "block_num": int,
      "classification": BlockType,
      "classification_confidence": float [0.0-1.0]
    }
  ],
  "total_blocks": int,
  "avg_classification_confidence": float,
  "model_used": str,
  "processing_cost": float,
  "timestamp": str
}
```

---

## 5 Essential Visualizations

### 1. Stat Cards (5 minutes to implement)
**Purpose**: Overview health check
**Data**: `report.csv` aggregates
**Metrics**: 
- Pages Processed: X/Y
- Avg Confidence: 0.XX
- Page Numbers Extracted: X/Y (%)
- Chapter Headings: X
- Region Distribution: Front X | Body X | Back X

### 2. Confidence Distribution Histogram (10 minutes)
**Purpose**: Identify ambiguous pages
**Data**: `report.csv[avg_classification_confidence]`
**Bins**: [0-0.80], [0.80-0.85], [0.85-0.90], [0.90-0.95], [0.95-1.0]
**Red Flag**: >10% of pages <0.85 confidence

### 3. Problem Pages Table (15 minutes)
**Purpose**: Direct action items for review
**Data**: `report.csv` filtered and sorted
**Criteria**: 
- Confidence < 0.80
- Region not classified (null)
- Sparse (<2 blocks) or dense (>20 blocks)
**Features**: Sortable by confidence, region, block count

### 4. Page Number Extraction Timeline (20 minutes)
**Purpose**: Detect numbering transitions and gaps
**Data**: `report.csv[page_num, printed_page_number, numbering_style]`
**Shows**:
- Which pages have extracted numbers (mark with ✓)
- Numbering style (roman vs arabic) transitions
- Gaps and anomalies
**Context**: Normal for front matter to have few numbers, expected transition roman→arabic

### 5. Chapter Boundary Detection (10 minutes)
**Purpose**: Validate build-structure readiness
**Data**: `report.csv[has_chapter_heading, page_num, printed_page_number]`
**Shows**:
- Total chapter headings detected
- Distribution by region (should be 0 in front/back, most in body)
- Chapter list with page and printed numbers

---

## Block Type Color Scheme

Use consistently across all visualizations:

```
CHAPTER_HEADING       → Red          (#E74C3C)
SECTION_HEADING       → Orange       (#E67E22)
BODY                  → Blue         (#3498DB)
HEADER / FOOTER       → Gray         (#95A5A6)
PAGE_NUMBER           → Purple       (#9B59B6)
FOOTNOTE / ENDNOTES   → Yellow       (#F1C40F)
TABLE                 → Green        (#2ECC71)
ILLUSTRATION_CAPTION  → Green        (#27AE60)
OCR_ARTIFACT          → Red X        (#C0392B)
```

Quality Indicators:
```
0.95-1.0   → Green  (✓)
0.85-0.95  → Yellow (⚠)
0.75-0.85  → Orange (⚠)
<0.75      → Red    (✗)
```

---

## Data Access Patterns

### Quick Stats
```python
import pandas as pd

report = pd.read_csv('labels/report.csv')

# Stat cards
total_pages = len(report)
avg_confidence = report['avg_classification_confidence'].mean()
num_extracted = report['page_number_extracted'].sum()
chapter_count = report['has_chapter_heading'].sum()

# Region breakdown
front = (report['page_region'] == 'front_matter').sum()
body = (report['page_region'] == 'body').sum()
back = (report['page_region'] == 'back_matter').sum()
```

### Problem Pages
```python
# Low confidence pages
low_conf = report[report['avg_classification_confidence'] < 0.80]

# Pages without region classification
no_region = report[report['page_region_classified'] == False]

# Outlier block counts (very sparse or dense)
sparse = report[report['total_blocks_classified'] < 2]
dense = report[report['total_blocks_classified'] > 20]
```

### Block Type Distribution
```python
import json
from pathlib import Path
from collections import Counter

block_types = Counter()
for page_file in Path('labels').glob('page_*.json'):
    with open(page_file) as f:
        data = json.load(f)
    for block in data.get('blocks', []):
        block_types[block['classification']] += 1

# Display top 10
for block_type, count in block_types.most_common(10):
    print(f"{block_type:20} {count:5} ({100*count/sum(block_types.values()):.1f}%)")
```

---

## Quality Interpretation

### Green Zone (No Action)
- Confidence: >0.90
- All blocks classified
- Page region identified
- 5-15 blocks per page
- Page numbers expected for region

### Yellow Zone (Spot Check)
- Confidence: 0.80-0.90
- Some unusual block counts
- Page numbers missing in body but page looks like intro
- Region transitions where expected

### Red Zone (Manual Review)
- Confidence: <0.80
- Region not classified (null)
- Extremely sparse (<2) or dense (>20) blocks
- Page numbers missing in body without reason
- Unusual region transitions

---

## Integration with Build-Structure Stage

Labels feeds to build-structure:
- `has_chapter_heading` → Chapter anchor points
- `printed_page_number` → Page mapping
- `page_region` → Structural context
- Block classifications → Content understanding

Build-structure readiness criteria:
- ✓ 20-30+ chapter headings detected
- ✓ Roman → Arabic numbering transition
- ✓ All regions (front/body/back) present
- ✓ <5% pages with confidence <0.80

---

## Dashboard Layout Template

```
┌─────────────────────────────────────────────────────┐
│ LABELS STAGE VIEWER                                 │
├─────────────────────────────────────────────────────┤
│ [Book Name] [Stage: labels]                         │
├─────────────────────────────────────────────────────┤
│ QUALITY OVERVIEW (Stat Cards)                       │
├─────────────────────────────────────────────────────┤
│ Pages: 442 | Confidence: 0.92 | Numbers: 287/442   │
│ Chapters: 24 | Front: 52 | Body: 368 | Back: 22    │
├─────────────────────────────────────────────────────┤
│ VISUALIZATIONS                                      │
├─────────────────────────────────────────────────────┤
│ [Confidence Histogram] [Region Dist] [Timeline]     │
│ [Block Types] [Extraction Success] [Chapters]       │
├─────────────────────────────────────────────────────┤
│ PAGES REQUIRING REVIEW                              │
├─────────────────────────────────────────────────────┤
│ [Sortable problem pages table]                      │
│ Click page to open visual viewer                    │
└─────────────────────────────────────────────────────┘
```

---

## Implementation Checklist

### Phase 1 (P0) - Essential
- [ ] Stat cards with 6-7 key metrics
- [ ] Confidence distribution histogram
- [ ] Problem pages table (sortable)
- [ ] Page number extraction timeline

### Phase 2 (P1) - High Value
- [ ] Block type distribution chart
- [ ] Chapter boundary detection list
- [ ] Page region distribution pie
- [ ] Visual page viewer with bbox overlays

### Phase 3 (P2) - Nice to Have
- [ ] Confidence vs extraction success scatter
- [ ] Cost-quality analysis
- [ ] Region transition flow diagram

---

## Testing Strategy

1. Use existing sample data: `~/Documents/book_scans/*/labels/`
2. Start with stat cards (simplest)
3. Verify data sources (report.csv, page_*.json)
4. Build visualizations incrementally
5. Compare patterns with Correction stage viewer

## References

- Full analysis: `docs/analysis/labels_stage_visualization_guide.md`
- Correction stage patterns: `docs/analysis/corrected_stage_visualization_guide.md`
- Label stage code: `pipeline/label/schemas.py`, `pipeline/label/__init__.py`
- Existing viewer: `tools/templates/labels/viewer.html`
