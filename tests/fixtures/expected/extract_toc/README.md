# Expected Results for extract-toc Stage

This directory contains ground truth expected results for extract-toc accuracy tests.

## Format

Each file is `{book_id}.json` containing:

```json
{
  "scan_id": "book-id",
  "finder_result": {
    "toc_found": true,
    "toc_page_range": {"start_page": 5, "end_page": 12},
    "structure_summary": {...}
  },
  "toc": {
    "entries": [
      {
        "entry_number": "I",
        "title": "Chapter Title",
        "level": 1,
        "level_name": "chapter",
        "printed_page_number": "1"
      },
      ...
    ]
  }
}
```

## Usage

Tests load these expected results and compare against actual stage outputs:

```python
from tests.fixtures.expected.extract_toc import load_expected_result

expected = load_expected_result("accidental-president")
# Run stage
# Compare outputs
```

## Updating

To update expected results for a book:
1. Manually verify the stage output is correct
2. Copy the corrected output to this file
3. Commit the change with explanation of why it's correct
