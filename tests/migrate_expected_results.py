#!/usr/bin/env python3
"""
Migrate expected results from old fixture structure to new compact format.

Old: tests/fixtures/extract_toc/{book}/.expected/find/finder_result.json
                                              /finalize/toc.json

New: tests/fixtures/expected/extract_toc/{book}.json
     {
       "scan_id": "book",
       "finder_result": {...},
       "toc": {...}
     }
"""

import json
from pathlib import Path
import shutil


def migrate_extract_toc_expected():
    """Migrate extract-toc expected results."""
    old_fixtures_dir = Path("tests/fixtures/extract_toc")
    new_expected_dir = Path("tests/fixtures/expected/extract_toc")

    # Create new directory
    new_expected_dir.mkdir(parents=True, exist_ok=True)

    migrated = []
    errors = []

    # Process each book
    for book_dir in old_fixtures_dir.iterdir():
        if not book_dir.is_dir() or book_dir.name.startswith('.') or book_dir.name == '__pycache__':
            continue

        book_id = book_dir.name
        expected_dir = book_dir / ".expected"

        if not expected_dir.exists():
            errors.append(f"{book_id}: No .expected directory")
            continue

        try:
            # Load expected results
            finder_file = expected_dir / "find" / "finder_result.json"
            toc_file = expected_dir / "finalize" / "toc.json"

            if not finder_file.exists() or not toc_file.exists():
                errors.append(f"{book_id}: Missing expected files")
                continue

            with open(finder_file) as f:
                finder_result = json.load(f)

            with open(toc_file) as f:
                toc = json.load(f)

            # Create compact expected result
            expected = {
                "scan_id": book_id,
                "finder_result": finder_result,
                "toc": toc
            }

            # Save to new location
            new_file = new_expected_dir / f"{book_id}.json"
            with open(new_file, 'w') as f:
                json.dump(expected, f, indent=2)

            migrated.append(book_id)
            print(f"✅ {book_id}")

        except Exception as e:
            errors.append(f"{book_id}: {str(e)}")
            print(f"❌ {book_id}: {e}")

    # Create README
    readme_content = """# Expected Results for extract-toc Stage

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
"""

    readme_file = new_expected_dir / "README.md"
    with open(readme_file, 'w') as f:
        f.write(readme_content)

    # Summary
    print(f"\n{'='*80}")
    print(f"MIGRATION SUMMARY")
    print(f"{'='*80}")
    print(f"Migrated: {len(migrated)} books")
    print(f"Errors: {len(errors)}")
    if errors:
        print("\nErrors:")
        for error in errors:
            print(f"  - {error}")

    print(f"\nNew expected results: tests/fixtures/expected/extract_toc/")
    print(f"Total files: {len(list(new_expected_dir.glob('*.json')))}")

    # Calculate size savings
    if old_fixtures_dir.exists():
        old_size = sum(f.stat().st_size for f in old_fixtures_dir.rglob('*') if f.is_file())
        new_size = sum(f.stat().st_size for f in new_expected_dir.rglob('*') if f.is_file())
        print(f"\nSize comparison:")
        print(f"  Old fixtures: {old_size / 1024 / 1024:.1f} MB")
        print(f"  New expected: {new_size / 1024:.1f} KB")
        print(f"  Savings: {(old_size - new_size) / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    migrate_extract_toc_expected()
