# ToC Ground Truth Dataset

This directory contains ground truth data for evaluating and testing the `extract-toc` stage.

## Setup

**Note:** The actual book data (OCR, images) is not included in the repository due to copyright restrictions.

To generate the dataset locally:

```bash
# Ensure you have processed books in your local book storage
# Then run the setup script
./tests/fixtures/toc_ground_truth/setup_ground_truth.sh
```

This will copy the necessary data from `~/Documents/book_scans/` (or `$BOOK_STORAGE_ROOT`) for the following books:
- fiery-peace
- admirals
- groves-bomb
- american-caesar
- hap-arnold

## Purpose

Enable rapid iteration on ToC extraction prompts by:
- Providing known-good extractions for comparison
- Testing prompt changes against real data
- Measuring extraction accuracy and variance
- Catching regressions before they hit production

## Structure

Each book is a **valid BookStorage directory** that can be used directly with the pipeline:

```
toc_ground_truth/
  {book-id}/                    # e.g., fiery-peace

    # Standard book directory structure
    metadata.json               # Book metadata
    source/
      page_0001.png             # Source images (pages 1-50)
      ...
      page_0050.png
    ocr-pages/
      paddle/page_*.json        # All OCR providers (pages 1-50)
      mistral/page_*.json
      olm/page_*.json

    # Expected outputs for validation
    .expected/
      find/
        finder_result.json      # Expected find phase output
      finalize/
        toc.json                # Expected final ToC (ground truth)
```

**Key Design:**
- No duplication: OCR files exist once in proper location
- Tests real code: Uses actual BookStorage API
- Self-contained: Each book is runnable through extract-toc stage
- Phase outputs in `.expected/` for comparison

## Books Included

1. **fiery-peace**: Complex 2-level hierarchy (15 books, 83 chapters)
2. **admirals**: Medium 2-level (11 parts, 35 chapters)
3. **groves-bomb**: Small 2-level (4 parts, 33 chapters)
4. **american-caesar**: Large flat structure (20 chapters)
5. **hap-arnold**: Large flat structure (31 chapters)

## Usage

### Testing Extraction Accuracy

```python
# tests/test_toc_extraction.py
from tests.fixtures.toc_ground_truth import load_ground_truth

def test_extract_toc_accuracy():
    for book in load_ground_truth():
        result = extract_toc_stage.run(book.scan_id)
        assert_toc_matches(result, book.expected_toc)
        assert_correct_ordering(result)
```

### Measuring Variance

```python
# Run extraction 10 times, measure agreement
results = []
for _ in range(10):
    result = extract_toc_stage.run("fiery-peace")
    results.append(result)

variance = measure_variance(results)
print(f"Entry order agreement: {variance.order_agreement}%")
print(f"Title match rate: {variance.title_match}%")
```

### A/B Testing Prompts

```python
# Compare old vs new prompt
old_results = run_with_prompt(old_prompt)
new_results = run_with_prompt(new_prompt)

improvement = compare_accuracy(old_results, new_results, ground_truth)
print(f"Accuracy improvement: {improvement}%")
```

## Maintenance

When updating ground truth:
1. Manually verify the extraction is correct
2. Update `expected_toc.json` or `expected_result.json`
3. Document any edge cases in `metadata.json`
4. Run full test suite to catch downstream impacts

## Notes

- Ground truth was extracted from production runs on 2025-11-20
- All extractions manually verified for correctness
- ToC page ordering issue in fiery-peace was corrected (BOOK III placement)
