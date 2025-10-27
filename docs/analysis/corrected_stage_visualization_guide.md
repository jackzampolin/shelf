# Corrected Stage Data Structure & Visualization Analysis

## Executive Summary

The Correction stage is a vision-based error correction layer that compares OCR output against actual page images using multimodal LLMs. It produces **sparse corrections** (only changed text) with rich quality metrics, enabling both before/after comparison and quality assessment. This analysis examines the data structures and recommends essential visualizations for a corrected stage viewer.

---

## 1. Report Schema Analysis

### Location
`/Users/johnzampolin/go/src/github.com/jackzampolin/scanshelf/pipeline/correction/schemas.py:133-147`

### CorrectionPageReport Structure

```python
class CorrectionPageReport(BaseModel):
    page_num: int                          # Page number
    total_corrections: int                 # Count of paragraphs corrected
    avg_confidence: float [0.0-1.0]       # Quality after correction
    text_similarity_ratio: float [0.0-1.0] # Similarity to OCR (1.0 = identical)
    characters_changed: int                # Edit magnitude
```

### Key Quality Metrics in Report

| Metric | Purpose | Interpretation |
|--------|---------|-----------------|
| **total_corrections** | Volume of changes | 1-5% = clean, 5-15% = normal, 20-40% = poor OCR, >40% = red flag |
| **avg_confidence** | Model's trust in corrections | >0.95 = high, 0.85-0.95 = normal, <0.85 = uncertain |
| **text_similarity_ratio** | How much changed vs OCR | 0.95-1.0 = minor fixes, 0.90-0.95 = normal, 0.85-0.90 = concerning, <0.85 = red flag |
| **characters_changed** | Edit distance magnitude | Complement to similarity ratio (high = major rewrites) |

### Report CSV Columns

When `report.csv` is generated, it contains these columns per page:
- `page_num` - Page identifier
- `total_corrections` - Number of corrected paragraphs
- `avg_confidence` - Average confidence score
- `text_similarity_ratio` - Similarity between OCR and corrected
- `characters_changed` - Character-level edit count

---

## 2. Page Output Schema Analysis

### Location
`/Users/johnzampolin/go/src/github.com/jackzampolin/scanshelf/pipeline/correction/schemas.py:86-104`

### CorrectionPageOutput Structure (corrected/page_*.json)

```python
class CorrectionPageOutput(BaseModel):
    page_number: int
    blocks: List[BlockCorrection]  # Sparse corrections only
    
    # Metadata
    model_used: str                # e.g., 'gpt-4o'
    processing_cost: float         # USD cost of this page
    timestamp: str                 # ISO timestamp
    
    # Summary statistics
    total_blocks: int              # Total blocks on page
    total_corrections: int         # Paragraphs with text changes
    avg_confidence: float          # Average confidence across all corrections
```

### BlockCorrection Structure

```python
class BlockCorrection(BaseModel):
    block_num: int                 # Matches OCR block number
    paragraphs: List[ParagraphCorrection]

class ParagraphCorrection(BaseModel):
    par_num: int                   # Paragraph number within block
    text: Optional[str]            # FULL corrected text (only if changed)
    notes: Optional[str]           # What was fixed (e.g., "Fixed hyphenation, 2 OCR errors")
    confidence: float [0.0-1.0]   # Confidence in this correction
```

### Design Philosophy

- **Sparse design**: Only blocks/paragraphs with changes are included
- **Preserves OCR structure**: Can't add/remove blocks or paragraphs (enforced by per-page schema)
- **Visual context**: Paired with source images for verification
- **Cost efficient**: Vision downsampling reduces tokens 50%

---

## 3. Checkpoint Metrics Schema

### Location
`/Users/johnzampolin/go/src/github.com/jackzampolin/scanshelf/pipeline/correction/schemas.py:111-126`

### CorrectionPageMetrics Structure (stored in .checkpoint file)

Extends `LLMPageMetrics` with:

```python
class CorrectionPageMetrics(LLMPageMetrics):
    # From LLMPageMetrics
    page_num: int
    processing_time_seconds: float
    cost_usd: float
    attempts: int
    tokens_total: int
    tokens_per_second: float
    model_used: str
    provider: str
    queue_time_seconds: float
    execution_time_seconds: float
    total_time_seconds: float
    ttft_seconds: Optional[float]
    usage: Dict[str, Any]
    
    # Correction-specific
    total_corrections: int         # Paragraphs corrected
    avg_confidence: float          # Quality after correction
    text_similarity_ratio: float   # Similarity to OCR
    characters_changed: int        # Character-level changes
```

### Metric Access Pattern

```python
# Via CheckpointManager
all_metrics = checkpoint.get_all_metrics()  # Dict[page_num, metrics_dict]
status = checkpoint.get_status()            # High-level status
```

---

## 4. Data Quality Indicators

Based on correction stage README and report generation:

### Text Similarity Ratio Interpretation

```
0.95-1.0   ✓ Expected    - OCR was good, minor fixes
0.90-0.95  ✓ Normal      - Moderate corrections applied
0.85-0.90  ⚠ Concerning  - Major rewrites (manual review recommended)
<0.85      ✗ Red flag    - Possible hallucination or poor OCR quality
```

### Confidence Distribution

```
>0.95      - High confidence corrections (over-confident if >85% pages)
0.85-0.95  - Normal range (expected for uncertain texts)
<0.85      - Low confidence (pages needing review)
```

### Correction Rate (as % of paragraphs)

```
1-5%       - Clean modern books
5-15%      - Technical/historical text
20-40%     - Poor OCR quality
>40%       - Requires manual verification
```

---

## 5. Visualization Recommendations

### Recommended Visualization Suite

#### 1. **Quality Score Card** (Top of Dashboard)

Display key statistics at a glance:

```
┌─────────────────────────────────────────────────────────────┐
│ CORRECTED STAGE OVERVIEW                                    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Pages Processed: 342/442                                   │
│  Total Corrections: 1,234 (8.2% of paragraphs)             │
│  Avg Confidence: 0.91                                       │
│  Avg Similarity: 0.93                                       │
│  Total Cost: $12.45                                         │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Data sources**: 
- `report.csv` aggregates (avg, sum, count)
- `checkpoint` status tracking

**Quality**: Shows overall health at a glance

---

#### 2. **Confidence Distribution Histogram**

Visualization type: **Horizontal bar histogram**

Shows how correction confidence is distributed across pages.

```
┌─────────────────────────────────────────────────────────────┐
│ CONFIDENCE SCORE DISTRIBUTION                               │
├─────────────────────────────────────────────────────────────┤
│ 0.95-1.0  │████████████████████   142 pages (41.5%)        │
│ 0.90-0.95 │██████████████         95 pages (27.8%)         │
│ 0.85-0.90 │████████               58 pages (16.9%)         │
│ <0.85     │███                    21 pages (6.1%)          │
├─────────────────────────────────────────────────────────────┤
│ Avg: 0.913 (±0.087)  Median: 0.925                         │
└─────────────────────────────────────────────────────────────┘
```

**Data source**: `report.csv[avg_confidence]`

**Why it matters**:
- Identifies pages with low confidence (manual review candidates)
- Red flag if >85% of pages have 0.95+ confidence (over-confident model)
- Normal distribution expected around 0.90-0.95

---

#### 3. **Similarity Ratio Distribution Histogram**

Visualization type: **Horizontal bar histogram with color coding**

Shows edit magnitude (how different corrected text is from OCR).

```
┌─────────────────────────────────────────────────────────────┐
│ TEXT SIMILARITY DISTRIBUTION (OCR vs Corrected)             │
├─────────────────────────────────────────────────────────────┤
│ 0.95-1.0  │██████████████████████  218 pages (63.7%)  ✓    │
│ 0.90-0.95 │████████████            102 pages (29.8%)  ✓    │
│ 0.85-0.90 │███                     15 pages (4.4%)   ⚠    │
│ <0.85     │█                        7 pages (2.0%)   ✗    │
├─────────────────────────────────────────────────────────────┤
│ Avg: 0.956 (±0.043)  Median: 0.968                         │
│ ⚠ 7 pages need review (similarity <0.85)                    │
└─────────────────────────────────────────────────────────────┘
```

**Data source**: `report.csv[text_similarity_ratio]`

**Why it matters**:
- Primary quality metric (low similarity = major rewrites)
- Color coding: green (expected), yellow (concerning), red (manual review)
- Identifies over-correction (when LLM changes too much)

---

#### 4. **Correction Volume vs Quality Scatter Plot**

Visualization type: **Scatter plot with page markers**

X-axis: Correction volume (% of paragraphs corrected)
Y-axis: Average confidence or similarity
Color: Cluster problematic pages

```
Confidence vs Correction Volume:
┌────────────────────────────────────────────────────────────┐
│ 1.0  ●                                                      │
│ 0.95 ●●●●●●●●●●●●● Expected area                         │
│ 0.90 ●●●●●●●●●●●●●●●●●                                   │
│ 0.85 ●●●●●ⓔ ⓔ ⓔ⚠ (review)                               │
│ 0.80 ●ⓔⓔⓔ ✗ ✗ ✗                                          │
└──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴────────┘
   0%  5%  10%  15%  20%  25%  30%  35%  40%
        % of paragraphs corrected
```

**Data source**: `report.csv[total_corrections, avg_confidence]`

**Why it matters**:
- Shows relationship between edit volume and confidence
- Outliers indicate problems:
  - Low confidence + high corrections = uncertain/hallucinated fixes
  - High confidence + low similarity = over-confident rewrites
  - High corrections + high confidence = possible over-correction

---

#### 5. **Cost-Quality Trade-off Chart**

Visualization type: **Line chart with dual axes**

Shows cost per page overlaid with quality metrics to identify efficiency issues.

```
┌────────────────────────────────────────────────────────────┐
│ COST vs QUALITY METRICS                                    │
├────────────────────────────────────────────────────────────┤
│ Cost: ─── Quality: ───                                     │
│                                                            │
│ $0.015 ┤                                                   │
│ $0.012 ┤  ╱╲      ╱╲                                      │
│ $0.009 ┤ ╱  ╲ ╱╲ ╱  ╲                                    │
│ $0.006 ┤╱    ╲╱  ╲╱    ╲                                  │
│ $0.003 ┤            ╲  ╱   ╱╲                             │
│      ┼─────────────────────────────────                   │
│ 1.00  │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓                        │
│ 0.95  │░░░░░░░░░░░░░░░░░░░░░░░░░                         │
│ 0.90  │                                                    │
│ 0.85  │                                                    │
└────────────────────────────────────────────────────────────┘
```

**Data source**: `checkpoint[cost_usd, total_time_seconds]`, `report.csv[avg_confidence]`

**Why it matters**:
- Identifies expensive pages with poor results (cost optimization)
- Highlights anomalies (e.g., high cost but low confidence)
- Helps optimize model/settings for future runs

---

#### 6. **Problem Pages Table** (Prioritized Review List)

Visualization type: **Sortable/filterable table**

The most actionable visualization - shows exactly which pages need manual review.

```
┌──────────────────────────────────────────────────────────────────┐
│ PAGES NEEDING REVIEW (Sorted by Severity)                        │
├──────────────────────────────────────────────────────────────────┤
│ Page │ Similarity │ Confidence │ Corrections │ Issue Type        │
├──────┼────────────┼────────────┼──────────────┼──────────────────┤
│ 145  │   0.72 ✗   │    0.78 ⚠   │    28/45    │ Over-correction  │
│ 203  │   0.81 ⚠   │    0.82 ⚠   │    22/52    │ Major rewrite    │
│  67  │   0.89 ⚠   │    0.91     │     8/34    │ Confidence dip   │
│ 421  │   0.79 ⚠   │    0.85 ⚠   │    19/41    │ Uncertain fixes  │
│ 312  │   0.73 ✗   │    0.80 ⚠   │    35/56    │ Over-correction  │
│                                                                    │
│ Summary: 5 pages need review | 2 critical | 3 concerning        │
└──────────────────────────────────────────────────────────────────┘
```

**Data source**: `report.csv` (sortable by any metric)

**Why it matters**:
- Direct action items for manual review
- Shows context: similarity, confidence, volume
- Allows filtering by issue type (low confidence, high edits, etc.)

---

#### 7. **Before/After Text Comparison Panel** (Per-Page)

Visualization type: **Side-by-side text diff view**

When clicking a page in problem table, show the actual changes.

```
┌───────────────────────────────────────────────────────────────────┐
│ PAGE 145 | Block 3 | Para 1                                      │
├─────────────────────────────┬─────────────────────────────────────┤
│ OCR OUTPUT (Original)       │ CORRECTED OUTPUT                    │
├─────────────────────────────┼─────────────────────────────────────┤
│ The quick brown fox         │ The quick brown fox                 │
│ jumps over the lazy dog.    │ jumps over the lazy dog.            │
│                             │                                     │
│ Tlie imrnediately response  │ The immediately response            │
│ was striking.               │ was striking.                       │
│                             │                                     │
│ Model: gpt-4o               │ Confidence: 0.85                    │
│ Cost: $0.006                │ Similarity: 0.92                    │
│ Timestamp: 2025-10-27...    │ Changes: 4 chars, 1 word           │
└─────────────────────────────┴─────────────────────────────────────┘
```

**Data source**: OCR output loaded from disk, corrected output from `corrected/page_*.json`

**Why it matters**:
- Direct verification of whether corrections are appropriate
- Shows confidence/similarity in context of actual text
- Enables quick spot-checking before approving results

---

### Implementation Priority Matrix

| Visualization | Priority | Effort | Impact | Recommendation |
|---------------|----------|--------|--------|-----------------|
| Stat Cards | P0 (must) | Low | Essential | Build first - foundation |
| Confidence Histogram | P0 (must) | Low | High | Shows problematic pages |
| Similarity Histogram | P0 (must) | Low | High | Primary quality metric |
| Scatter Plot | P1 | Medium | High | Reveals patterns/outliers |
| Cost-Quality Chart | P2 | Medium | Medium | Optimization insights |
| Problem Pages Table | P0 (must) | Low | Critical | Direct action items |
| Before/After Viewer | P1 | High | High | Verification tool |

---

## 6. Comparison Strategy: OCR vs Corrected Visualization

### Challenge
Correction stage DOESN'T produce full page text - it produces **sparse corrections only** (block_num, par_num, text). Need to reconstruct full corrected text by merging OCR + corrections.

### Solution: Smart Reconstruction

1. **Load OCR output** (`ocr/page_*.json`)
2. **Load corrections** (`corrected/page_*.json`)
3. **Reconstruct corrected text** by applying corrections:
   ```python
   corrected_text = {}
   for block_idx, block in enumerate(ocr_blocks):
       for para_idx, para in enumerate(block['paragraphs']):
           # Get correction if it exists
           correction = find_correction(block_idx, para_idx)
           if correction and correction['text'] is not None:
               corrected_text = correction['text']
           else:
               corrected_text = para['text']  # Keep original OCR
   ```

### Before/After Comparison Types

#### Type 1: Full Page Text Comparison
```
Metric: Aggregate text similarity (all paragraphs)
Source: report.csv[text_similarity_ratio]
Shows: Overall edit magnitude per page
```

#### Type 2: Block-Level Comparison
```
UI Element: Collapsible block list
Shows: Which blocks had corrections
Metrics: Block-level similarity, correction count
```

#### Type 3: Paragraph-Level Diff
```
UI Element: Highlighted diff view
Shows: Exact character-level changes
Color coding:
  - Green: Additions (OCR errors fixed)
  - Red: Deletions (unnecessary text)
  - Yellow: Modifications (changed words)
```

#### Type 4: Confidence Overlay
```
Visualization: Text with confidence background color
Lighter → higher confidence
Darker → lower confidence (needs review)
```

---

## 7. Data Files Reference

### Report CSV Structure
**File**: `corrected/report.csv`

Columns generated by `BaseStage.generate_report()`:
```
page_num,total_corrections,avg_confidence,text_similarity_ratio,characters_changed
1,5,0.92,0.96,12
2,8,0.89,0.94,28
3,3,0.95,0.98,5
...
```

### Page Output Files
**Files**: `corrected/page_*.json`

```json
{
  "page_number": 42,
  "blocks": [
    {
      "block_num": 0,
      "paragraphs": [
        {
          "par_num": 0,
          "text": "The corrected text...",
          "notes": "Fixed OCR errors",
          "confidence": 0.92
        }
      ]
    }
  ],
  "model_used": "gpt-4o",
  "processing_cost": 0.0056,
  "timestamp": "2025-10-27T14:32:15.123456",
  "total_blocks": 3,
  "total_corrections": 8,
  "avg_confidence": 0.91
}
```

### Checkpoint Metrics
**File**: `.checkpoint`

```json
{
  "page_metrics": {
    "1": {
      "page_num": 1,
      "processing_time_seconds": 12.45,
      "cost_usd": 0.0067,
      "tokens_total": 2048,
      "model_used": "gpt-4o",
      "total_corrections": 5,
      "avg_confidence": 0.92,
      "text_similarity_ratio": 0.96,
      "characters_changed": 12
    }
  }
}
```

---

## 8. Recommended Metrics Dashboard Layout

```
┌──────────────────────────────────────────────────────────────────┐
│ SCANSHELF: CORRECTION STAGE VIEWER                               │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│  [← Back] Book: accidental-president | Stage: corrected         │
│                                                                   │
├─────────────────────────────────────────────────────────────────────┤
│ QUALITY OVERVIEW                                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                   │
│  Pages: 342/442         Corrections: 1,234 (8.2%)                 │
│  Cost: $12.45           Avg Confidence: 0.91                      │
│  Avg Similarity: 0.93   Time: 2h 14m                              │
│                                                                   │
├─────────────────────────────────────────────────────────────────────┤
│ METRICS & DISTRIBUTIONS                                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                   │
│ ┌──────────────────────────┐  ┌──────────────────────────┐       │
│ │ Confidence Distribution  │  │ Similarity Distribution   │       │
│ │                          │  │                          │       │
│ │ 0.95+ │████████ 142      │  │ 0.95+ │█████████ 218     │       │
│ │ 0.90+ │██████   95       │  │ 0.90+ │████   102        │       │
│ │ 0.85+ │████     58       │  │ 0.85+ │█   15            │       │
│ │ <0.85 │██   21          │  │ <0.85 │   7              │       │
│ └──────────────────────────┘  └──────────────────────────┘       │
│                                                                   │
│ ┌──────────────────────────────────────────────────────────┐     │
│ │ Corrections vs Quality (Scatter)                         │     │
│ │ [Shows outliers and clustering]                         │     │
│ └──────────────────────────────────────────────────────────┘     │
│                                                                   │
├─────────────────────────────────────────────────────────────────────┤
│ PAGES REQUIRING REVIEW                                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                   │
│ Showing 5 critical issues:                                       │
│                                                                   │
│ [145] Similarity 0.72 ✗ | Confidence 0.78 ⚠ | 28/45 → Review   │
│ [203] Similarity 0.81 ⚠ | Confidence 0.82 ⚠ | 22/52 → Review   │
│ [421] Similarity 0.79 ⚠ | Confidence 0.85 ⚠ | 19/41 → Review   │
│ [ 67] Similarity 0.89 ⚠ | Confidence 0.91   |  8/34 → Check     │
│ [312] Similarity 0.73 ✗ | Confidence 0.80 ⚠ | 35/56 → Review   │
│                                                                   │
│ [View All] [Filter by Issue Type]                               │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

---

## 9. Quality Interpretation Guidelines

### Green Zone (No Action Required)
- Similarity: 0.95-1.0
- Confidence: >0.90
- Corrections: <15%
- Action: Accept as-is

### Yellow Zone (Spot Check)
- Similarity: 0.85-0.95
- Confidence: 0.85-0.90
- Corrections: 15-30%
- Action: Quick review of changes

### Red Zone (Manual Review Required)
- Similarity: <0.85
- Confidence: <0.85
- Corrections: >40%
- Action: Deep dive, possibly reject

---

## 10. Key Insights from Correction Stage

### Why These Metrics Matter

1. **text_similarity_ratio**
   - Most important metric for detecting over-correction
   - Shows whether LLM rewrote text excessively
   - Combined with characters_changed = full edit picture

2. **avg_confidence**
   - Model's self-assessment of correction quality
   - Low confidence = uncertain fixes (should be skeptical)
   - High confidence on low-quality pages = model is overconfident

3. **total_corrections (as percentage)**
   - Indicates book OCR quality
   - Baseline for what's "normal"
   - Helps detect anomalies (e.g., one page with 50% corrections)

4. **characters_changed**
   - Complements similarity ratio
   - High change count + high similarity = only necessary fixes
   - High change count + low similarity = over-correction

### Correlation Insights

Expected patterns:
- High corrections + High similarity = good quality OCR + good corrections
- Low corrections + High similarity = clean OCR
- High corrections + Low similarity = possible hallucination
- Low corrections + Low similarity = model couldn't match structure

---

## Conclusion

The Correction stage produces rich quality data enabling three levels of visualization:

1. **Overview Level** (Stats, distributions) - Health check
2. **Problem Detection** (Histograms, tables) - Find problematic pages
3. **Verification Level** (Before/after diffs) - Manual review support

Recommended implementation order:
1. Stat cards + problem pages table (P0)
2. Confidence and similarity histograms (P0)
3. Scatter plot showing correlations (P1)
4. Before/after diff viewer (P1)
5. Cost-quality analysis chart (P2)

This mirrors the OCR stage approach but tailored for correction's unique concern: detecting over-correction and ensuring edit quality.
