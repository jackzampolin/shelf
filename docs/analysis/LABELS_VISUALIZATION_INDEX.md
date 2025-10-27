# Labels Stage Visualization Analysis - Complete Index

This directory contains comprehensive analysis and recommendations for visualizing the Labels stage in the scanshelf pipeline.

## Overview

The **Labels stage** performs vision-based page number extraction and block classification without text correction. It produces rich structural metadata (page numbers, regions, block types) that enables downstream structure extraction and book understanding.

This analysis focuses on visualizations to:
1. Assess extraction quality (page numbers, regions, block classifications)
2. Identify structural boundaries (chapters, sections)
3. Validate readiness for build-structure stage
4. Enable manual verification of problematic pages

---

## Document Structure

### 1. **labels_stage_visualization_guide.md** (COMPREHENSIVE)
**Purpose**: Complete technical analysis of Labels stage data structures and visualization recommendations
**Length**: ~900 lines
**Contains**:
- Full Report/Output/Metrics schema analysis with examples
- Complete 38-type block classification taxonomy
- Data quality interpretation guidelines
- 9 detailed visualization specifications with ASCII mockups
- Implementation priority matrix
- Color coding schemes
- Dashboard layout templates
- Integration with build-structure stage

**Best for**: Understanding the complete picture, architectural decisions, deep dives

---

### 2. **LABELS_VISUALIZATION_QUICK_REFERENCE.md** (FAST REFERENCE)
**Purpose**: Practical quick-reference guide for developers implementing visualizations
**Length**: ~250 lines
**Contains**:
- Data structure summary (report.csv columns, page_*.json schema)
- 5 essential visualizations (1-2 paragraphs each)
- Block type color scheme with hex codes
- Python code snippets for common operations
- Quality interpretation zones (green/yellow/red)
- Integration points with build-structure
- Implementation checklist (3 phases)

**Best for**: Implementation, quick lookups, design decisions

---

### 3. **LABELS_VISUALIZATION_IMPLEMENTATION_EXAMPLES.md** (CODE EXAMPLES)
**Purpose**: Concrete working code for each visualization
**Length**: ~500 lines
**Contains**:
- Backend (Python/Flask) implementations for all visualizations
- Frontend (HTML/JavaScript) templates and styling
- Chart.js integration examples
- Data loading and error handling patterns
- Color coding functions
- Full HTML dashboard template
- Testing strategies

**Best for**: Copy-paste implementation, debugging, integration patterns

---

### 4. **LABELS_VISUALIZATION_INDEX.md** (THIS DOCUMENT)
**Purpose**: Navigation and quick reference for all analysis documents
**Contains**: Overview, document guide, key metrics summary, quick decision trees

---

## Key Findings Summary

### Data Available
- **report.csv**: Aggregated per-page metrics (high-level overview)
- **page_*.json**: Full classification data (detailed inspection)
- **Source images**: Visual verification context
- **Checkpoint**: Processing metrics and timing

### 5 Essential Visualizations

| # | Visualization | Type | Effort | Impact | Purpose |
|---|---|---|---|---|---|
| 1 | **Stat Cards** | Cards | 5 min | Essential | Overall health check |
| 2 | **Confidence Distribution** | Histogram | 10 min | High | Identify ambiguous pages |
| 3 | **Problem Pages Table** | Table | 15 min | Critical | Action items for review |
| 4 | **Page Number Timeline** | Line chart | 20 min | High | Detect numbering transitions |
| 5 | **Chapter Detection** | List | 10 min | High | Structure extraction readiness |

### Quality Indicators
- **avg_classification_confidence**: [0.0-1.0] - Block classification quality
  - >0.90 = High confidence, 0.80-0.90 = Normal, <0.80 = Ambiguous
- **page_number_extracted**: Boolean - Printed page number found
  - Normal to be False for front matter, chapter starts
  - Concerning if False for body pages
- **page_region_classified**: Boolean - Region identified
  - Should be True for all pages
  - False indicates uncertain classification
- **has_chapter_heading**: Boolean - Chapter start detected
  - Indicator of structural boundaries
  - Expected: 20-30+ chapters per typical book

---

## Implementation Roadmap

### Phase 1 (P0) - Essential (1-2 hours)
Essential for MVP labels viewer:
1. Stat cards - 5 min
2. Confidence distribution histogram - 10 min
3. Problem pages table - 15 min
4. Page number extraction timeline - 20 min

### Phase 2 (P1) - High Value (2-3 hours)
Significant additional value:
5. Block type distribution chart - 15 min
6. Chapter boundary detection list - 10 min
7. Page region distribution pie - 5 min
8. Visual page viewer with overlays - 60 min

### Phase 3 (P2) - Nice to Have (1-2 hours)
Polish and insights:
9. Confidence vs extraction scatter plot - 30 min
10. Cost-quality analysis - 20 min
11. Region transition flow diagram - 15 min

---

## Quick Decision Tree

### "I want to implement this, where do I start?"

1. **Need implementation code?** 
   - See: `LABELS_VISUALIZATION_IMPLEMENTATION_EXAMPLES.md`
   - Start with stat cards (simplest)

2. **Need to understand the data?**
   - See: `LABELS_VISUALIZATION_QUICK_REFERENCE.md` Section "Data Structure Summary"
   - Full details: `labels_stage_visualization_guide.md` Sections 1-3

3. **Need to decide what to build?**
   - See: `LABELS_VISUALIZATION_QUICK_REFERENCE.md` Section "5 Essential Visualizations"
   - Priority matrix: `labels_stage_visualization_guide.md` Section 5

4. **Need color scheme / design reference?**
   - See: `LABELS_VISUALIZATION_QUICK_REFERENCE.md` Section "Block Type Color Scheme"
   - Full scheme: `labels_stage_visualization_guide.md` Section 6

5. **Need to understand quality interpretation?**
   - See: `LABELS_VISUALIZATION_QUICK_REFERENCE.md` Section "Quality Interpretation"
   - Details: `labels_stage_visualization_guide.md` Section 4

---

## Block Type Taxonomy (Quick Reference)

**38 block types across 8 categories:**

**Structure** (7):
- CHAPTER_HEADING, SECTION_HEADING, BODY, HEADER, FOOTER, PAGE_NUMBER, QUOTE

**Front Matter** (7):
- TITLE_PAGE, COPYRIGHT, DEDICATION, TABLE_OF_CONTENTS, PREFACE, FOREWORD, INTRODUCTION

**Back Matter** (6):
- EPILOGUE, APPENDIX, GLOSSARY, ACKNOWLEDGMENTS, BIBLIOGRAPHY, INDEX

**Special Content** (6):
- ILLUSTRATION_CAPTION, TABLE, MAP_LABEL, DIAGRAM_LABEL, PHOTO_CREDIT, CAPTION

**References** (3):
- FOOTNOTE, ENDNOTES, EPIGRAPH

**Fallback** (2):
- OCR_ARTIFACT, OTHER

See `labels_stage_visualization_guide.md` Section 3 for full descriptions.

---

## Integration Points

### With Build-Structure Stage
Labels stage feeds critical data:
- `has_chapter_heading` → Chapter anchor points
- `printed_page_number` → Page mapping
- `page_region` → Structural context
- Block classifications → Content understanding

**Readiness criteria**:
- ✓ 20-30+ chapter headings detected
- ✓ Roman → Arabic numbering transition
- ✓ All regions present (front/body/back)
- ✓ <5% pages with confidence <0.80

---

## Data Access Examples

### Quick Python Pattern
```python
import pandas as pd

# Load report (high-level)
report = pd.read_csv('labels/report.csv')

# Stat cards
pages = len(report)
avg_conf = report['avg_classification_confidence'].mean()
extracted = report['page_number_extracted'].sum()

# Problem pages
problems = report[report['avg_classification_confidence'] < 0.80]
```

### Load Full Page Data
```python
import json

with open('labels/page_0050.json') as f:
    page = json.load(f)

blocks = page['blocks']  # List of BlockClassification
printed_num = page['printed_page_number']
region = page['page_region']
```

---

## Testing Your Implementation

1. **Use existing data**: `~/Documents/book_scans/*/labels/`
2. **Start simple**: Build stat cards first (verify data loading works)
3. **Compare patterns**: Mimic Correction stage viewer patterns
4. **Verify calculations**: Sample 5-10 pages manually
5. **Test edge cases**: Empty blocks, sparse pages, region transitions

---

## File Locations (Absolute Paths)

### Analysis Documents
- Full guide: `/Users/johnzampolin/go/src/github.com/jackzampolin/scanshelf/docs/analysis/labels_stage_visualization_guide.md`
- Quick ref: `/Users/johnzampolin/go/src/github.com/jackzampolin/scanshelf/docs/analysis/LABELS_VISUALIZATION_QUICK_REFERENCE.md`
- Examples: `/Users/johnzampolin/go/src/github.com/jackzampolin/scanshelf/docs/analysis/LABELS_VISUALIZATION_IMPLEMENTATION_EXAMPLES.md`
- Index: `/Users/johnzampolin/go/src/github.com/jackzampolin/scanshelf/docs/analysis/LABELS_VISUALIZATION_INDEX.md`

### Source Code
- Schemas: `/Users/johnzampolin/go/src/github.com/jackzampolin/scanshelf/pipeline/label/schemas.py`
- Implementation: `/Users/johnzampolin/go/src/github.com/jackzampolin/scanshelf/pipeline/label/__init__.py`
- Existing viewer: `/Users/johnzampolin/go/src/github.com/jackzampolin/scanshelf/tools/templates/labels/viewer.html`

### Sample Data
- Report CSV: `~/Documents/book_scans/[scan_id]/labels/report.csv`
- Page files: `~/Documents/book_scans/[scan_id]/labels/page_*.json`

---

## Key References

### Within This Analysis
- Full taxonomy: `labels_stage_visualization_guide.md` Section 3
- Quality interpretation: `LABELS_VISUALIZATION_QUICK_REFERENCE.md` Section "Quality Interpretation"
- Implementation checklist: `LABELS_VISUALIZATION_QUICK_REFERENCE.md` Section "Implementation Checklist"
- Code examples: `LABELS_VISUALIZATION_IMPLEMENTATION_EXAMPLES.md`

### In Codebase
- Label stage design: `pipeline/label/README.md`
- Prompts: `pipeline/label/prompts.py`
- Report generation: `pipeline/label/__init__.py:generate_report()`

### Related Analysis
- Correction stage patterns: `docs/analysis/corrected_stage_visualization_guide.md`
- OCR stage viewer: `tools/templates/stage/ocr_viewer.html`
- Architecture: `docs/architecture/`

---

## Contact Points

For questions about:
- **Data structure**: See `labels_stage_visualization_guide.md` Sections 1-2
- **What to build**: See `LABELS_VISUALIZATION_QUICK_REFERENCE.md` Section "5 Essential Visualizations"
- **How to build**: See `LABELS_VISUALIZATION_IMPLEMENTATION_EXAMPLES.md`
- **Design choices**: See `labels_stage_visualization_guide.md` Section 6
- **Integration**: See `labels_stage_visualization_guide.md` Section 9

---

## Summary

The Labels stage analysis provides everything needed to build effective visualizations:

1. **Complete understanding** of what data is available and how it's structured
2. **Concrete recommendations** for 5-10 essential visualizations
3. **Design guidance** (colors, layouts, quality indicators)
4. **Implementation code** (Python, HTML, JavaScript, Chart.js)
5. **Quality standards** (what metrics mean, when pages need review)
6. **Integration context** (how this feeds downstream stages)

All visualizations work with existing data already generated by the Labels stage - no new data collection needed.

**Estimated implementation time for MVP (Phase 1): 1-2 hours**

