# Session 6: Internet Archive E2E Validation

**Previous Session**: Test migration complete (134 tests, 31 unit tests in 18s)

**Current State**: Downloaded IA ground truth data (51.6 MB) for Roosevelt autobiography

---

## What We Have

1. **Clean Test Suite**
   - 134 tests total (removed 15 stale e2e tests)
   - 31 unit tests pass in 18s using committed fixtures (105KB)
   - Clear unit/integration separation with pytest markers

2. **IA Ground Truth Data Downloaded**
   - `abbyy.gz` (18 MB) - XML with character-level coordinates and confidence
   - `hocr.html` (32 MB) - Alternative OCR format
   - `djvu_text.txt` (1.5 MB) - Plain text fulltext
   - `page_numbers.json` (106 KB) - Page number mapping

3. **Full Roosevelt Book**
   - 637 pages processed through: OCR → Correct (has needs_review)
   - Fix and Structure stages NOT yet run on full book
   - Location: ~/Documents/book_scans/roosevelt-autobiography

---

## Session 6 Goals

**Objective**: Create e2e validation test that runs full pipeline and compares against IA ground truth

### Task 1: Explore ABBYY Data Structure (30 min)

The ABBYY XML has rich structure we need to understand:

```bash
# Decompress and explore
gunzip -c tests/fixtures/roosevelt/ia_ground_truth/abbyy.gz | less

# Key questions:
# - How is text organized by page?
# - Can we extract plain text per page easily?
# - What confidence scores are available?
# - How are bounding boxes structured?
```

### Task 2: Create Simple ABBYY Parser (1 hour)

**File**: `tests/validation/abbyy_parser.py`

Goal: Extract plain text per page from ABBYY for comparison

```python
class ABBYYParser:
    """Parse ABBYY GZ format to extract ground truth text."""

    def __init__(self, abbyy_gz_path):
        # Load and parse XML
        pass

    def get_page_text(self, page_num: int) -> str:
        """Get clean text for a specific page."""
        # Extract text from page
        pass

    def get_page_count(self) -> int:
        """Total pages in document."""
        pass
```

### Task 3: Create Text Comparison Helper (30 min)

**File**: `tests/validation/comparison.py`

```python
def calculate_accuracy(our_text: str, ground_truth: str) -> dict:
    """
    Compare our OCR/corrected text against IA ground truth.

    Returns:
        {
            'character_accuracy': 0.95,  # 95% accuracy
            'word_accuracy': 0.97,
            'cer': 0.05,  # Character Error Rate
            'sample_diff': '...'  # First few differences
        }
    """
    pass
```

### Task 4: Create E2E Validation Test (1 hour)

**File**: `tests/test_ia_validation.py`

```python
@pytest.mark.e2e
@pytest.mark.slow
def test_full_pipeline_validation():
    """
    Full pipeline e2e test with IA validation.

    1. Use existing Roosevelt OCR (already done)
    2. Run Correct stage on full book (~$10, 1 hour)
    3. Run Fix stage on flagged pages (~$1, 15 min)
    4. Compare final output vs IA ground truth
    5. Generate quality report

    Expected: >95% accuracy vs IA
    Cost: ~$12
    Duration: ~1.5 hours
    """
    # Load IA ground truth
    # Run pipeline stages
    # Compare outputs
    # Assert quality thresholds
    pass
```

### Task 5: Run the E2E Test (2-3 hours)

```bash
# This will cost ~$12 and take 2-3 hours
pytest tests/test_ia_validation.py::test_full_pipeline_validation -v -s

# Expected output:
# - Pipeline completes successfully
# - OCR accuracy: ~95%
# - Corrected accuracy: ~97%
# - Final accuracy: ~98%
# - Quality report generated
```

---

## Key Decisions Needed

1. **Which stages to validate?**
   - Option A: Just OCR vs IA ABBYY (fast, no cost)
   - Option B: Full pipeline OCR → Correct → Fix (slow, $12)
   - **Recommend**: Start with Option A, then run Option B

2. **How to handle differences?**
   - IA data isn't perfect either
   - Need to define "acceptable" error rate
   - Focus on detecting regressions, not absolute perfection

3. **Test execution**
   - Mark as `@pytest.mark.e2e` (not run by default)
   - Separate validation from development tests
   - Run manually before releases

---

## Quick Start Commands

```bash
# Explore ABBYY structure
gunzip -c tests/fixtures/roosevelt/ia_ground_truth/abbyy.gz | head -500

# Check what we have
ls -lh tests/fixtures/roosevelt/ia_ground_truth/
ls -lh ~/Documents/book_scans/roosevelt-autobiography/

# Start with simple parser
mkdir -p tests/validation
touch tests/validation/abbyy_parser.py
touch tests/validation/comparison.py

# Create test file
touch tests/test_ia_validation.py
```

---

## Success Criteria

- [ ] Can extract text from ABBYY XML
- [ ] Can compare our OCR vs IA ground truth
- [ ] Accuracy calculation works (CER, word accuracy)
- [ ] E2E test runs full pipeline
- [ ] Quality report shows >95% accuracy
- [ ] Validation test is repeatable

---

**Next Session Focus**: Build the validation infrastructure, then run the full e2e test
