# Labels Stage Data Structure & Visualization Analysis

## Executive Summary

The Labels stage performs **vision-based page number extraction and block classification** without text correction. It produces rich structural metadata (page numbers, regions, block types) that enables downstream structure extraction and book understanding. This analysis examines the data structures and recommends essential visualizations for a labels stage viewer.

---

## 1. Report Schema Analysis

### Location
`/Users/johnzampolin/go/src/github.com/jackzampolin/scanshelf/pipeline/label/schemas.py:168-191`

### LabelPageReport Structure

```python
class LabelPageReport(BaseModel):
    page_num: int                                    # PDF page number
    printed_page_number: Optional[str]              # Book page (e.g., 'ix', '45', None)
    numbering_style: Optional[Literal["roman", "arabic", "none"]]
    page_region: Optional[PageRegion]               # front_matter/body/back_matter
    page_number_extracted: bool                     # Was a printed number found?
    page_region_classified: bool                    # Was region identified?
    total_blocks_classified: int                    # Count of blocks classified
    avg_classification_confidence: float [0.0-1.0] # Quality of classifications
    
    # Chapter/section structure (for build-structure stage)
    has_chapter_heading: bool                       # Contains CHAPTER_HEADING block?
    has_section_heading: bool                       # Contains SECTION_HEADING block?
    chapter_heading_text: Optional[str]            # First 100 chars of chapter text
```

### Sample report.csv Data

```
page_num,printed_page_number,numbering_style,page_region,page_number_extracted,page_region_classified,total_blocks_classified,avg_classification_confidence,has_chapter_heading,has_section_heading,chapter_heading_text
1,,,front_matter,False,True,4,0.95,False,False,
2,,,front_matter,False,True,11,0.941,False,False,
5,x,roman,front_matter,True,True,4,0.95,False,False,
6,xi,roman,front_matter,True,True,4,0.938,False,False,
13,5,arabic,front_matter,True,True,4,0.9,True,True,
14,6,arabic,body,True,True,4,0.912,True,True,
```

### Key Quality Metrics in Report

| Metric | Purpose | Interpretation |
|--------|---------|-----------------|
| **page_number_extracted** | Was printed page number found? | False on early/chapter pages (normal), False on body pages (concerning) |
| **page_region_classified** | Was region classified? | Should be True for all pages (False = uncertain classification) |
| **total_blocks_classified** | Count of blocks identified | Varies by page (sparse pages 2-5 blocks, dense pages 15+ blocks) |
| **avg_classification_confidence** | Quality of block classification | >0.90 = high confidence, 0.80-0.90 = normal, <0.80 = ambiguous pages |
| **has_chapter_heading** | Does page contain chapter start? | Indicator of structural boundaries for build-structure stage |

---

## 2. Page Output Schema Analysis

### Location
`/Users/johnzampolin/go/src/github.com/jackzampolin/scanshelf/pipeline/label/schemas.py:79-129`

### LabelPageOutput Structure (labels/page_*.json)

```python
class LabelPageOutput(BaseModel):
    # Page identification
    page_number: int
    
    # Printed page number extraction (from vision analysis)
    printed_page_number: Optional[str]              # e.g., 'ix', '45', None
    numbering_style: Optional[Literal["roman", "arabic", "none"]]
    page_number_location: Optional[Literal["header", "footer", "none"]]
    page_number_confidence: float [0.0-1.0]        # 1.0 if no number found
    
    # Page region classification (from position)
    page_region: Optional[PageRegion]               # front_matter/body/back_matter/toc_area
    page_region_confidence: Optional[float]         # Region classification quality
    
    # Classified blocks (NO text correction)
    blocks: List[BlockClassification]               # Array of classifications
    
    # Processing metadata
    model_used: str                                 # e.g., 'gpt-4o'
    processing_cost: float
    timestamp: str
    
    # Summary statistics
    total_blocks: int
    avg_classification_confidence: float
```

### BlockClassification Structure

```python
class BlockClassification(BaseModel):
    block_num: int                  # Matches OCR block number (1-based)
    classification: BlockType       # One of 38 types (see taxonomy below)
    classification_confidence: float [0.0-1.0]
```

### Sample page_*.json Data

```json
{
  "page_number": 72,
  "printed_page_number": null,
  "numbering_style": null,
  "page_number_location": null,
  "page_number_confidence": 1.0,
  "page_region": "body",
  "page_region_confidence": 0.95,
  "blocks": [
    {
      "block_num": 1,
      "classification": "CHAPTER_HEADING",
      "classification_confidence": 0.98
    },
    {
      "block_num": 2,
      "classification": "BODY",
      "classification_confidence": 0.95
    },
    {
      "block_num": 3,
      "classification": "BODY",
      "classification_confidence": 0.95
    }
  ],
  "model_used": "x-ai/grok-4-fast",
  "processing_cost": 0.0010894,
  "timestamp": "2025-10-24T09:45:39.989603",
  "total_blocks": 3,
  "avg_classification_confidence": 0.96
}
```

### Design Philosophy

- **Sparse block data**: Only classification + confidence, no text (text is in OCR)
- **Vision-first**: Uses page IMAGE for page numbers and visual structure signals
- **Structure-focused**: Enables downstream table of contents extraction
- **Block count constrained**: Exactly matches OCR block count (validates consistency)

---

## 3. Block Type Taxonomy (38 Types)

### Structure Classification

**Front Matter** (Roman numerals):
- `TITLE_PAGE` - Book title page
- `COPYRIGHT` - Copyright/publication info
- `DEDICATION` - Dedication page
- `TABLE_OF_CONTENTS` - Table of Contents (visual list)
- `PREFACE` - Author preface
- `FOREWORD` - Introduction/foreword by another author
- `INTRODUCTION` - Book introduction

**Main Content** (Arabic numerals):
- `CHAPTER_HEADING` - Chapter start (visual marker: large text + whitespace)
- `SECTION_HEADING` - Section within chapter
- `BODY` - Regular body text
- `QUOTE` - Block quotes (indented)
- `EPIGRAPH` - Quote at chapter start
- `FOOTNOTE` / `ENDNOTES` - Reference notes

**Back Matter**:
- `BIBLIOGRAPHY` - Bibliography/references
- `APPENDIX` - Appendix section
- `GLOSSARY` - Glossary of terms
- `INDEX` - Index pages
- `ACKNOWLEDGMENTS` - Acknowledgments section
- `EPILOGUE` - Closing/epilogue

**Structural Elements**:
- `HEADER` - Page header (top 10%)
- `FOOTER` - Page footer (bottom 20%)
- `PAGE_NUMBER` - Page number marker

**Special Content**:
- `ILLUSTRATION_CAPTION` - Caption for images
- `CAPTION` - Generic caption (maps to ILLUSTRATION_CAPTION)
- `TABLE` - Tabular data
- `MAP_LABEL` - Geographic/map labels
- `DIAGRAM_LABEL` - Timeline/chart labels
- `PHOTO_CREDIT` - Image attribution
- `OCR_ARTIFACT` - Garbled text from OCR errors

**Fallback**:
- `OTHER` - Catch-all (use sparingly)

---

## 4. Data Quality Indicators

### PageRegion Classification

```
front_matter → body → back_matter
             ↑ transitions marked by numbering style changes ↑
```

**Quality patterns**:
- Roman numerals → Arabic numerals = correct transition to main content
- Numbering style changes mid-document = potential OCR errors
- Gaps in numbering sequence = acceptable at section boundaries

### Page Number Extraction Quality

```
Perfect extraction (confidence 0.90-0.99):
- Clear printed number in standard location (header/footer)
- Consistent position across pages
- Valid sequence (no reversals or duplicates)

Uncertain extraction (confidence 0.70-0.89):
- Number visible but unusual placement
- Ambiguous OCR vs printed number
- Sequence anomaly (jump or reversal) - requires visual validation

Not extracted (confidence 1.0):
- No visible page number
- Front matter / chapter starts (normal)
- Blank pages / decorative pages
```

### Block Classification Quality

```
High confidence (0.90-1.0):
- Multiple clear visual signals (size, position, whitespace)
- Consistent with surrounding pages
- Clear structural boundaries

Normal confidence (0.80-0.90):
- Some signals present but ambiguous
- Position-based inference needed
- Borderline classifications (quote vs body)

Low confidence (<0.80):
- Ambiguous visual structure
- Pages with mixed content types
- Unusual layout or formatting
```

---

## 5. Visualization Recommendations

### Visualization Priority Matrix

| Visualization | Priority | Effort | Impact | Purpose |
|---------------|----------|--------|--------|---------|
| **Stat Cards** | P0 (must) | Low | Essential | Overall health check |
| **Page Number Extraction Timeline** | P0 (must) | Low | High | Detect missing/anomalous numbers |
| **Page Region Distribution** | P0 (must) | Low | High | Verify front/body/back transitions |
| **Block Type Histogram** | P0 (must) | Low | Medium | Understand content distribution |
| **Confidence Distribution** | P0 (must) | Low | High | Identify ambiguous pages |
| **Problem Pages Table** | P0 (must) | Low | Critical | Direct action items |
| **Chapter Boundary Detection** | P1 | Medium | High | Verify structure extraction readiness |
| **Visual Page Viewer** | P1 | Medium | High | Verify classifications visually |

---

### Essential Visualization Suite

#### 1. **Quality Score Card** (Top of Dashboard)

Display key statistics at a glance:

```
┌─────────────────────────────────────────────────────────┐
│ LABELS STAGE OVERVIEW                                  │
├─────────────────────────────────────────────────────────┤
│                                                        │
│  Pages Processed: 442/442 (100%)                       │
│  Avg Classification Confidence: 0.92                   │
│  Page Numbers Extracted: 287/442 (64.9%)              │
│  Chapter Headings Detected: 24                         │
│  Front Matter: 52 | Body: 368 | Back Matter: 22       │
│  Avg Blocks per Page: 8.2                             │
│  Total Cost: $0.87                                     │
│                                                        │
└─────────────────────────────────────────────────────────┘
```

**Data sources**: 
- `report.csv` aggregates (sum, avg, count)
- `checkpoint` completion status

**Quality**: Shows overall health and structure immediately

---

#### 2. **Page Number Extraction Timeline**

Visualization type: **Line chart with visual markers**

Shows progress of page number extraction across the document to detect:
- Which sections lack printed numbers (normal vs concerning)
- Numbering style transitions (roman → arabic)
- Gaps and anomalies in numbering sequence

```
┌────────────────────────────────────────────────────────┐
│ PRINTED PAGE NUMBER EXTRACTION TIMELINE                │
├────────────────────────────────────────────────────────┤
│                                                        │
│  50 │  ✓ ✓ ✓ ✓          [ROMAN NUMERALS]  │           │
│  40 │  ✓ ✓ ✓ ✓ ✓ ✓ ✓ ✓  [FRONT MATTER]   │           │
│  30 │                                    ╱            │
│     │ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ╱ ─ ─           │
│  20 │                               1 2 3... [ARABIC]│
│  10 │✓✓✓✓✓✓✓✓✓✓ ✓ ✓ ✓ ✓ ✓          [SCATTERED]     │
│   0 │                                                │
│     └──────────────────────────────────────────────────│
│      0    50   100   150   200   250   300   350   400│
│                    PDF Page Number                     │
│                                                        │
│  ✓ = Page number found                               │
│  - = No page number (chapter start, blank, etc.)    │
│                                                        │
│ Detected transition: Roman (1-100) → Arabic (101+)   │
└────────────────────────────────────────────────────────┘
```

**Data source**: `report.csv[page_num, printed_page_number, numbering_style]`

**Why it matters**:
- Shows distribution of extracted page numbers across document
- Highlights region transitions (roman → arabic numbering = correct structure)
- Identifies problematic areas (unexpected gaps, reversals)
- Context for build-structure stage (where ToC boundaries are)

---

#### 3. **Page Region Distribution** 

Visualization type: **Stacked bar chart + pie chart**

Shows the breakdown of front matter, body, and back matter pages:

```
┌────────────────────────────────────────────────────────┐
│ PAGE REGION CLASSIFICATION BREAKDOWN                   │
├────────────────────────────────────────────────────────┤
│                                                        │
│  Front Matter │████████ 52 (11.8%)                    │
│  Body Matter  │████████████████████████████ 368 (83.3%)│
│  Back Matter  │███ 22 (5.0%)                          │
│                                                        │
│  Pie Chart:   Front 11.8%                             │
│               ╱─────────╲                              │
│              ╱           ╲  Body                        │
│             │   83.3%    │  83.3%                      │
│              ╲           ╱                              │
│               ╲────┬────╱ Back 5.0%                     │
│                                                        │
│  Region Confidence:                                    │
│  - All pages classified (front_matter/body/back_matter)│
│  - Avg confidence: 0.93 (high)                        │
│                                                        │
└────────────────────────────────────────────────────────┘
```

**Data source**: `report.csv[page_region]`, aggregated by value

**Why it matters**:
- Validates document structure expectations (should have all three regions)
- Quick check for misclassified pages (unexpected region ratios)
- Context for downstream merge stage (knows which pages are structural)

---

#### 4. **Block Classification Confidence Distribution**

Visualization type: **Horizontal histogram**

Shows how confident the model is in its block classifications:

```
┌─────────────────────────────────────────────────────┐
│ BLOCK CLASSIFICATION CONFIDENCE DISTRIBUTION         │
├─────────────────────────────────────────────────────┤
│ 0.95-1.0  │████████████████████  318 pages (71.9%) │
│ 0.90-0.95 │████████████          87 pages (19.7%)  │
│ 0.85-0.90 │████                 28 pages (6.3%)   │
│ 0.80-0.85 │█                      8 pages (1.8%)   │
│ <0.80     │                       1 page  (0.2%)   │
├─────────────────────────────────────────────────────┤
│ Avg: 0.923 | Median: 0.950 | StdDev: 0.034        │
│ ⚠ 37 pages have confidence < 0.90 (review)       │
└─────────────────────────────────────────────────────┘
```

**Data source**: `report.csv[avg_classification_confidence]`

**Why it matters**:
- Identifies pages with uncertain block classifications
- Red flag if many pages have <0.85 confidence (OCR quality issues)
- Normal distribution expected around 0.90-0.95
- Context for merge stage (which pages need extra scrutiny)

---

#### 5. **Block Type Distribution** 

Visualization type: **Horizontal bar chart (count) + pie chart (by frequency)**

Shows what content types appear in the book:

```
┌─────────────────────────────────────────────────────┐
│ BLOCK TYPE FREQUENCY (across all pages)             │
├─────────────────────────────────────────────────────┤
│ BODY              │█████████████████████ 1456 (48.2%)│
│ SECTION_HEADING   │████████               245 (8.1%) │
│ CHAPTER_HEADING   │██████                 158 (5.2%) │
│ FOOTER            │████                   124 (4.1%) │
│ FOOTNOTE          │████                   119 (3.9%) │
│ HEADER            │████                   118 (3.9%) │
│ TABLE             │███                    89  (2.9%) │
│ ILLUSTRATION_CAPTION│██                   67  (2.2%) │
│ QUOTE             │██                     45  (1.5%) │
│ BIBLIOGRAPHY      │█                      32  (1.1%) │
│ [Other types]     │████                   155 (5.1%) │
│                                                     │
│ Total blocks classified: 3,018                      │
│ Avg blocks per page: 8.2                            │
│                                                     │
└─────────────────────────────────────────────────────┘
```

**Data source**: Load all `labels/page_*.json` files, aggregate block classifications

**Why it matters**:
- Understanding book composition (fiction vs academic vs illustrated)
- Validates classification consistency (e.g., footnotes only in body)
- Shows presence of special content (tables, illustrations, diagrams)
- Input to build-structure stage (what elements to extract)

---

#### 6. **Page Number Extraction Quality Histogram**

Visualization type: **Horizontal histogram with status indicators**

Shows effectiveness of page number extraction by region:

```
┌────────────────────────────────────────────────────┐
│ PAGE NUMBER EXTRACTION SUCCESS RATE                │
├────────────────────────────────────────────────────┤
│ ROMAN (front_matter):                             │
│   Extracted  │████████████ 48 pages (92.3%)  ✓    │
│   Not found  │█               4 pages (7.7%)  ⚠   │
│                                                   │
│ ARABIC (body):                                    │
│   Extracted  │██████████████ 321 pages (87.2%) ✓  │
│   Not found  │███                47 pages (12.8%)⚠ │
│                                                   │
│ BACK MATTER (mixed):                             │
│   Extracted  │████████  8 pages (36.4%)       ⚠   │
│   Not found  │██████████████ 14 pages (63.6%) -  │
│                                                   │
│ Summary: 377 of 442 pages (85.3%)               │
│ Missing page numbers: Normal for chapter starts  │
│         and back matter (not concerning)         │
└────────────────────────────────────────────────────┘
```

**Data source**: `report.csv[page_number_extracted, page_region]`

**Why it matters**:
- Shows extraction success by region (different expectations per region)
- Roman numeral success vs Arabic success comparison
- Identifies systematic extraction failures (e.g., all page numbers in footers missed)

---

#### 7. **Problem Pages Table** (Prioritized Review List)

Visualization type: **Sortable/filterable table with severity indicators**

The most actionable visualization - shows exactly which pages need review:

```
┌────────────────────────────────────────────────────────────┐
│ PAGES REQUIRING REVIEW (Sorted by Severity)               │
├────────────────────────────────────────────────────────────┤
│ Page │ Region       │ Confidence │ Blocks │ Issue Type    │
├──────┼──────────────┼────────────┼────────┼───────────────┤
│ 145  │ body   ✓     │ 0.72   ✗   │   3    │ Low confidence│
│ 203  │ back_m ✓     │ 0.81   ⚠   │   2    │ Sparse page  │
│  87  │ body   ✓     │ 0.85   ⚠   │  14    │ High variance│
│ 421  │ front  ✓     │ 0.78   ⚠   │   5    │ Low confidence│
│ 312  │ body   ✓     │ 0.88       │   8    │ Check region │
│                                                            │
│ Summary: 5 pages flagged for review                       │
│ Filters: [Region] [Confidence] [Block Count]             │
│                                                            │
│ Legend: ✓ Region classified, ✗ <0.75 confidence,        │
│         ⚠ 0.75-0.85 confidence, - Region not classified │
└────────────────────────────────────────────────────────────┘
```

**Data source**: `report.csv` (sortable/filterable by all columns)

**Quality thresholds**:
- Flag if `avg_classification_confidence < 0.80`
- Flag if `page_region_classified = False`
- Flag if `total_blocks < 2` or `total_blocks > 20` (sparse/dense outliers)
- Flag if unusual block distributions for region (e.g., chapter heading in body)

**Why it matters**:
- Direct action items for manual review
- Context: region, confidence, block count
- Allows prioritization (sort by confidence, region, etc.)

---

#### 8. **Chapter Boundary Detection** (For build-structure)

Visualization type: **Timeline with markers + context list**

Shows detected chapter starts for downstream table of contents extraction:

```
┌─────────────────────────────────────────────────────┐
│ CHAPTER HEADING DETECTION                           │
├─────────────────────────────────────────────────────┤
│                                                     │
│ Pages with CHAPTER_HEADING blocks:  24 detected    │
│ Pages with SECTION_HEADING blocks:  31 detected    │
│                                                     │
│ Detected Chapters (page, printed_num):              │
│   1. Page 50  (printed: "1")     [CHAPTER_HEADING]  │
│   2. Page 84  (printed: "2")     [CHAPTER_HEADING]  │
│   3. Page 120 (printed: "3")     [CHAPTER_HEADING]  │
│   4. Page 167 (printed: "4")     [CHAPTER_HEADING]  │
│   ... (20 more chapters) ...                        │
│                                                     │
│ Distribution across document:                       │
│ ├─ Front matter (0-15%): 0 chapters ✓             │
│ ├─ Body (15-85%): 24 chapters ✓                   │
│ └─ Back matter (85-100%): 0 chapters ✓            │
│                                                     │
│ Ready for build-structure stage ✓                  │
└─────────────────────────────────────────────────────┘
```

**Data source**: `report.csv[has_chapter_heading, page_num, printed_page_number]`

**Why it matters**:
- Validation for downstream table of contents extraction
- Shows density and distribution of structural boundaries
- Feeds directly into build-structure stage as anchor points
- Helps identify missing or extra chapter markers

---

#### 9. **Visual Page Viewer** (Per-Page Inspection)

Visualization type: **Image + overlay + metadata sidebar**

When clicking a page in the problem table, show:

```
┌────────────────────────────────────┬──────────────────┐
│ PAGE 145 - Label Visualization     │ Page Metadata    │
├────────────────────────────────────┼──────────────────┤
│                                    │ Printed #: null  │
│ [Page Image with overlays]         │ Region: body ✓   │
│ - Block bboxes colored by type    │ Blocks: 3        │
│ - Page number marker (if found)    │ Confidence: 0.72 │
│ - Chapter heading highlight       │ Model: gpt-4o    │
│                                    │                  │
│ [Canvas with bbox overlays]        │ Block Details:   │
│ - Red: CHAPTER_HEADING (conf: 0.98)│                  │
│ - Blue: BODY (conf: 0.75) ⚠       │ 1. CHAPTER_HEADING│
│ - Orange: FOOTER (conf: 0.88)     │    Conf: 0.98    │
│                                    │                  │
│                                    │ 2. BODY          │
│                                    │    Conf: 0.75 ⚠ │
│                                    │                  │
│                                    │ 3. FOOTER        │
│                                    │    Conf: 0.88    │
└────────────────────────────────────┴──────────────────┘
```

**Data sources**: 
- Source image from `source/page_*.png`
- OCR bboxes from `ocr/page_*.json` 
- Label classifications from `labels/page_*.json`
- Color mapping from block type taxonomy

**Why it matters**:
- Direct visual verification of classifications
- Inspect confidence scores in context
- See what the model classified and how confident it was
- Identify if visual signals were missed (e.g., chapter marker not detected)

---

## 6. Visualization Implementation Strategy

### Data Flow Pattern

```
report.csv (aggregates)
    ↓
Stat cards, histograms, tables ← Quick overview

checkpoint (page metrics)
    ↓
Timeline, distributions ← Pattern analysis

page_*.json (detailed)
    ↓
Visual viewer, problem analysis ← Verification
```

### Color Coding Scheme

Consistent across all visualizations:

```
Block Types:
- CHAPTER_HEADING      → Red (danger/important)
- SECTION_HEADING      → Orange (secondary structure)
- BODY                 → Blue (content)
- HEADER/FOOTER        → Gray (structural)
- PAGE_NUMBER          → Purple (metadata)
- FOOTNOTE/ENDNOTES    → Yellow (references)
- TABLE/ILLUSTRATION   → Green (special content)
- OCR_ARTIFACT         → Red X (error)

Quality Indicators:
- 0.95-1.0    → Green (✓ high confidence)
- 0.85-0.95   → Yellow (⚠ normal range)
- 0.75-0.85   → Orange (⚠ needs review)
- <0.75       → Red (✗ problematic)
```

### Key Metrics Dashboard Layout

```
┌──────────────────────────────────────────────────────────┐
│ SCANSHELF: LABELS STAGE VIEWER                           │
├──────────────────────────────────────────────────────────┤
│ [← Back] Book: modest-lovelace | Stage: labels          │
├──────────────────────────────────────────────────────────┤
│ QUALITY OVERVIEW (Stat Cards)                            │
├──────────────────────────────────────────────────────────┤
│ Pages: 442 | Confidence: 0.92 | Page Numbers: 287/442   │
│ Chapters: 24 | Front: 52 | Body: 368 | Back: 22         │
├──────────────────────────────────────────────────────────┤
│ VISUALIZATIONS                                           │
├──────────────────────────────────────────────────────────┤
│                                                          │
│ [Page Number Timeline] [Region Distribution] [Confidence]│
│                                                          │
│ [Block Type Distribution] [Extraction Success] [Chapters]│
│                                                          │
├──────────────────────────────────────────────────────────┤
│ PAGES REQUIRING REVIEW                                  │
├──────────────────────────────────────────────────────────┤
│ [Sortable table with 5-10 problematic pages]            │
│ Click to open visual page viewer                        │
└──────────────────────────────────────────────────────────┘
```

---

## 7. Data Access Patterns

### From report.csv

```python
import pandas as pd

# Load report
report = pd.read_csv('labels/report.csv')

# Stat cards
total_pages = len(report)
avg_confidence = report['avg_classification_confidence'].mean()
pages_with_numbers = report['page_number_extracted'].sum()
chapter_pages = report['has_chapter_heading'].sum()

# Confidence distribution (histogram)
confidence_bins = pd.cut(report['avg_classification_confidence'], 
                         bins=[0, 0.8, 0.85, 0.9, 0.95, 1.0])
print(confidence_bins.value_counts().sort_index())

# Problem pages (table)
problem_pages = report[
    (report['avg_classification_confidence'] < 0.80) |
    (report['page_region_classified'] == False)
]

# Region distribution
region_dist = report['page_region'].value_counts()
```

### From page_*.json

```python
import json
from pathlib import Path

# Load single page
page_path = Path('labels/page_0050.json')
with open(page_path) as f:
    page_data = json.load(f)

# Extract block info
blocks = page_data['blocks']
block_types = [b['classification'] for b in blocks]
confidence_scores = [b['classification_confidence'] for b in blocks]

# Page metadata
printed_num = page_data['printed_page_number']
region = page_data['page_region']
model = page_data['model_used']
cost = page_data['processing_cost']
```

---

## 8. Quality Interpretation Guidelines

### Green Zone (No Action Required)
- Confidence: >0.90
- All blocks classified
- Page region identified
- Page numbers where expected
- Action: Accept as-is

### Yellow Zone (Spot Check)
- Confidence: 0.80-0.90
- Some blocks uncertain
- Sparse or dense pages
- Page numbers missing but location makes sense
- Action: Quick visual review

### Red Zone (Manual Review Required)
- Confidence: <0.80
- Region not classified (null)
- Very sparse (<2 blocks) or very dense (>20 blocks)
- Page numbers missing in body
- Action: Visual inspection, possibly reclassify

---

## 9. Integration with Build-Structure Stage

The Labels stage feeds critical data to build-structure:

```
Labels Output → Build-Structure Input
─────────────────────────────────────
has_chapter_heading → Chapter anchor points
chapter_heading_text → Chapter titles (after merge)
printed_page_number → Page mapping
page_region → Structural context
block classifications → Content type understanding
```

**Key metrics for build-structure readiness**:
- ✓ At least 20-30 chapter headings detected (for typical books)
- ✓ Page numbering transitions correctly (roman → arabic)
- ✓ Regions classified correctly (front → body → back)
- ✓ <5% of pages with confidence <0.80

---

## 10. Implementation Priority

### Phase 1 (P0 - Essential)
1. Stat cards (5 min)
2. Confidence distribution histogram (10 min)
3. Problem pages table (15 min)
4. Page number extraction timeline (20 min)

### Phase 2 (P1 - High Value)
5. Block type distribution (15 min)
6. Chapter boundary detection (10 min)
7. Page region distribution (5 min)
8. Visual page viewer with overlays (60 min)

### Phase 3 (P2 - Nice to Have)
9. Confidence vs extraction success scatter (30 min)
10. Cost-quality analysis (20 min)

---

## 11. Conclusion

The Labels stage produces rich structural metadata enabling:

1. **Overview Level** (Stat cards, distributions) - Health check
2. **Problem Detection** (Histograms, tables) - Find problematic pages
3. **Structural Understanding** (Timeline, chapter detection) - Build-structure readiness
4. **Verification Level** (Visual viewer) - Manual review support

**Visualization Philosophy**:
- Focus on **structure extraction quality** (unlike Correction which focuses on text quality)
- Enable **downstream build-structure success** (chapters, regions, numbering)
- Support **visual verification** (page images + classification overlays)
- Prioritize **actionable insights** (problem pages, confidence scores, region validation)

**Data is already available** in existing structures:
- `report.csv` - All high-level metrics
- `page_*.json` - Full classification details
- Source images - Visual verification context
- Checkpoint data - Processing metrics

Recommended implementation order mirrors the Correction stage pattern but tailored to structure extraction concerns.
