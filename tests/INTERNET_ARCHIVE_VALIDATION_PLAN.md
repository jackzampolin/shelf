# Internet Archive Validation Test Plan

**Purpose**: Validate Scanshelf pipeline outputs against Internet Archive's structured OCR data

**Roosevelt Book**: https://archive.org/details/theorooseauto00roosrich

---

## Available IA Structured Data

From Internet Archive, we can download:

### 1. **ABBYY GZ** - Structured OCR with coordinates
- Format: Compressed XML with word-level coordinates
- Contains: Text, bounding boxes, confidence scores, formatting
- Use: Ground truth for OCR accuracy and layout

### 2. **HOCR HTML** - HTML OCR format
- Format: HTML with microformat annotations
- Contains: Text with bbox attributes, page structure
- Use: Validation of text extraction and page layout

### 3. **OCR Page Index (JSON)** - Page-level metadata
- Format: JSON array of page info
- Contains: Page numbers, text snippets, word counts
- Use: Page-level structure validation

### 4. **Page Numbers (JSON)** - Page number mapping
- Format: JSON mapping scan pages to book pages
- Contains: Physical page → logical page mapping
- Use: Validate chapter/page numbering

### 5. **OCR Search Text (TXT)** - Plain text
- Format: Single text file of full book
- Contains: Raw text extraction
- Use: End-to-end text extraction accuracy

---

## Validation Test Plan

### Phase 1: Download IA Data (Setup)

**Script**: `tests/fixtures/download_ia_data.py`

```python
#!/usr/bin/env python3
"""
Download Internet Archive structured data for Roosevelt book.

Downloads to: tests/fixtures/roosevelt/ia_source/
- abbyy.gz (Structured OCR XML)
- hocr.html (HTML OCR format)
- page_index.json (Page metadata)
- page_numbers.json (Page mapping)
- fulltext.txt (Plain text)

Run once to set up validation data (~5-10MB total).
"""

import requests
from pathlib import Path

def download_ia_files():
    base_url = "https://archive.org/download/theorooseauto00roosrich"
    ia_dir = Path(__file__).parent / "roosevelt" / "ia_source"
    ia_dir.mkdir(parents=True, exist_ok=True)

    files = {
        "abbyy.gz": "theorooseauto00roosrich_abbyy.gz",
        "hocr.html": "theorooseauto00roosrich_hocr.html",
        "page_index.json": "theorooseauto00roosrich_page_numbers.json",
        "fulltext.txt": "theorooseauto00roosrich_djvu.txt"
    }

    for local_name, ia_filename in files.items():
        url = f"{base_url}/{ia_filename}"
        output = ia_dir / local_name

        if output.exists():
            print(f"✓ {local_name} already exists")
            continue

        print(f"⬇️  Downloading {local_name}...")
        response = requests.get(url)
        response.raise_for_status()

        with open(output, 'wb') as f:
            f.write(response.content)
        print(f"✅ Downloaded {local_name} ({len(response.content) / 1024:.1f} KB)")

    print("\n✅ IA data ready for validation")

if __name__ == "__main__":
    download_ia_files()
```

---

### Phase 2: OCR Validation Tests

**File**: `tests/test_ia_ocr_validation.py`

```python
"""
Validate OCR stage against Internet Archive ABBYY data.

Compares:
- Text extraction accuracy
- Bounding box coordinates
- Page structure detection
- Confidence scores (if available)
"""

import pytest
from pathlib import Path


class TestOCRvsABBYY:
    """Compare Scanshelf OCR against IA ABBYY OCR."""

    def test_text_extraction_accuracy(self, roosevelt_fixtures):
        """Compare extracted text with ABBYY ground truth."""
        # Load our OCR
        our_ocr = load_scanshelf_ocr(roosevelt_fixtures / "ocr" / "page_0010.json")

        # Load IA ABBYY
        ia_text = load_abbyy_text("page_0010")

        # Compare text similarity (use difflib or Levenshtein)
        similarity = calculate_similarity(our_ocr['text'], ia_text)

        assert similarity > 0.95, f"OCR accuracy: {similarity:.2%}"

    def test_bounding_box_accuracy(self, roosevelt_fixtures):
        """Compare bounding boxes with ABBYY coordinates."""
        our_bbox = load_scanshelf_bbox(roosevelt_fixtures / "ocr" / "page_0010.json")
        ia_bbox = load_abbyy_bbox("page_0010")

        # Calculate IoU (Intersection over Union)
        iou = calculate_iou(our_bbox, ia_bbox)

        assert iou > 0.80, f"BBox IoU: {iou:.2%}"

    def test_page_structure_detection(self, roosevelt_fixtures):
        """Validate header/footer/body classification."""
        our_structure = load_scanshelf_structure(roosevelt_fixtures / "ocr" / "page_0010.json")
        ia_structure = load_abbyy_structure("page_0010")

        # Compare region types
        assert our_structure['headers'] == ia_structure['headers']
        assert our_structure['footers'] == ia_structure['footers']
```

---

### Phase 3: Structure Validation Tests

**File**: `tests/test_ia_structure_validation.py`

```python
"""
Validate Structure stage against Internet Archive metadata.

Compares:
- Chapter detection
- Page numbering
- Table of contents extraction
"""

class TestStructurevsIA:
    """Compare Scanshelf structure against IA metadata."""

    def test_chapter_detection(self, roosevelt_full_book):
        """Validate detected chapters against IA TOC."""
        our_chapters = load_scanshelf_chapters(roosevelt_full_book)
        ia_toc = load_ia_toc()

        # Compare chapter titles and page numbers
        for ours, theirs in zip(our_chapters, ia_toc):
            assert_similar(ours['title'], theirs['title'], threshold=0.90)
            assert abs(ours['page'] - theirs['page']) <= 2  # Allow 2-page variance

    def test_page_number_mapping(self, roosevelt_full_book):
        """Validate physical→logical page mapping."""
        our_mapping = load_scanshelf_page_numbers(roosevelt_full_book)
        ia_mapping = load_ia_page_numbers()

        # Compare mappings
        assert our_mapping == ia_mapping
```

---

### Phase 4: End-to-End Text Validation

**File**: `tests/test_ia_e2e_validation.py`

```python
"""
End-to-end validation: Compare final output with IA fulltext.
"""

class TestE2EvsIA:
    """Compare complete pipeline output with IA fulltext."""

    def test_full_book_text_accuracy(self, roosevelt_full_book):
        """Compare assembled book text with IA fulltext.txt."""
        our_text = load_scanshelf_fulltext(roosevelt_full_book)
        ia_text = load_ia_fulltext()

        # Overall similarity
        similarity = calculate_text_similarity(our_text, ia_text)

        assert similarity > 0.90, f"Full book accuracy: {similarity:.2%}"

    def test_chapter_text_preservation(self, roosevelt_full_book):
        """Validate no text lost in chapter assembly."""
        our_chapters = load_scanshelf_chapters(roosevelt_full_book)
        our_assembled = "".join(c['text'] for c in our_chapters)

        original_ocr = load_all_scanshelf_ocr(roosevelt_full_book)

        # Verify assembly preserved text
        assert len(our_assembled) >= len(original_ocr) * 0.98
```

---

## Metrics to Track

### OCR Stage
- **Text Accuracy**: Character-level accuracy vs ABBYY
- **BBox IoU**: Bounding box intersection over union
- **Structure Precision**: Header/footer/body classification accuracy

### Correct Stage
- **Error Detection Rate**: % of real errors found
- **False Positive Rate**: % of corrections that were wrong
- **Text Preservation**: % of original text preserved

### Structure Stage
- **Chapter Detection F1**: Precision/recall of chapter boundaries
- **Page Number Accuracy**: % correct page number mappings
- **TOC Extraction**: Accuracy of table of contents

### End-to-End
- **Overall Text Similarity**: Final output vs IA fulltext
- **Processing Time**: Time per page for each stage
- **Cost per Page**: API costs for correction/structure

---

## Implementation Plan

### Week 1: Setup
- [ ] Download IA data for Roosevelt
- [ ] Parse ABBYY GZ format
- [ ] Parse HOCR HTML format
- [ ] Create helper functions for comparison

### Week 2: OCR Validation
- [ ] Implement text similarity comparison
- [ ] Implement bbox IoU calculation
- [ ] Add structure classification validation
- [ ] Run on 5 test pages

### Week 3: Structure Validation
- [ ] Implement chapter detection comparison
- [ ] Validate page number mapping
- [ ] Compare TOC extraction
- [ ] Full book validation

### Week 4: Reporting
- [ ] Create validation report generator
- [ ] Add CI integration for validation
- [ ] Document acceptable thresholds
- [ ] Publish validation results

---

## Success Criteria

**Minimum Acceptable**:
- Text Accuracy: >90%
- BBox IoU: >75%
- Structure Precision: >85%
- Chapter Detection F1: >80%

**Target**:
- Text Accuracy: >95%
- BBox IoU: >85%
- Structure Precision: >90%
- Chapter Detection F1: >90%

---

## Notes

1. **Why Roosevelt?**
   - Public domain
   - Well-structured IA data
   - Already processed through our pipeline
   - Representative of biography genre

2. **Validation != Testing**
   - Tests verify code works correctly
   - Validation measures output quality against ground truth
   - Both are essential for production confidence

3. **ABBYY as Ground Truth**
   - Internet Archive uses ABBYY FineReader (industry standard)
   - Not perfect, but best available ground truth
   - Our goal: match or exceed ABBYY quality

4. **Cost Considerations**
   - Validation tests should NOT make API calls
   - Compare against stored outputs only
   - Can be run frequently without cost

---

**Status**: Plan Created
**Next Step**: Implement download script and parse ABBYY format
