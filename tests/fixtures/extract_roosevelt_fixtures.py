#!/usr/bin/env python3
"""
Extract Roosevelt test fixtures from full book scan.

Creates a committed test dataset with:
- Source PDFs (if available)
- OCR JSON
- Corrected JSON
- Structured output (if available)

Selected pages:
- page_0010: Early chapter, normal text
- page_0050: Mid-book, typical content
- page_0100: Later content
- page_0200: Deep in book
- page_0500: Near end

Total size: ~2-5MB (acceptable for git)
"""

import shutil
import json
from pathlib import Path


def extract_fixtures():
    """Extract Roosevelt pages as test fixtures."""

    # Source and destination
    roosevelt_dir = Path.home() / "Documents" / "book_scans" / "roosevelt-autobiography"
    fixture_dir = Path(__file__).parent / "roosevelt"

    if not roosevelt_dir.exists():
        print(f"❌ Roosevelt book not found at {roosevelt_dir}")
        print("   Run: uv run python ar.py pipeline roosevelt-autobiography")
        return False

    # Clean and create fixture directory
    if fixture_dir.exists():
        shutil.rmtree(fixture_dir)
    fixture_dir.mkdir()

    # Selected test pages
    test_pages = [10, 50, 100, 200, 500]

    # Copy metadata
    metadata_src = roosevelt_dir / "metadata.json"
    if metadata_src.exists():
        with open(metadata_src) as f:
            metadata = json.load(f)

        # Update for fixture
        metadata['fixture'] = True
        metadata['test_pages'] = test_pages

        with open(fixture_dir / "metadata.json", 'w') as f:
            json.dump(metadata, f, indent=2)
        print(f"✅ Copied metadata")

    # Create subdirectories
    for subdir in ['ocr', 'corrected', 'structured']:
        (fixture_dir / subdir).mkdir()

    # Extract pages
    extracted = {
        'ocr': 0,
        'corrected': 0,
        'structured': 0
    }

    for page_num in test_pages:
        page_filename = f"page_{page_num:04d}.json"

        # OCR
        ocr_src = roosevelt_dir / "ocr" / page_filename
        if ocr_src.exists():
            shutil.copy(ocr_src, fixture_dir / "ocr" / page_filename)
            extracted['ocr'] += 1

        # Corrected
        corrected_src = roosevelt_dir / "corrected" / page_filename
        if corrected_src.exists():
            shutil.copy(corrected_src, fixture_dir / "corrected" / page_filename)
            extracted['corrected'] += 1

    # Copy structured output if exists (entire directory is useful)
    structured_src = roosevelt_dir / "structured"
    if structured_src.exists():
        # Copy full_book.md (small, useful for tests)
        full_book = structured_src / "full_book.md"
        if full_book.exists():
            shutil.copy(full_book, fixture_dir / "structured" / "full_book.md")

        # Copy metadata
        struct_meta = structured_src / "metadata.json"
        if struct_meta.exists():
            shutil.copy(struct_meta, fixture_dir / "structured" / "metadata.json")
            extracted['structured'] = 1

    print(f"\n📊 Extraction Summary:")
    print(f"   OCR pages: {extracted['ocr']}")
    print(f"   Corrected pages: {extracted['corrected']}")
    print(f"   Structured files: {extracted['structured']}")

    # Calculate size
    total_size = sum(
        f.stat().st_size
        for f in fixture_dir.rglob('*')
        if f.is_file()
    )
    print(f"   Total size: {total_size / 1024 / 1024:.2f} MB")

    if total_size > 10 * 1024 * 1024:  # 10MB
        print(f"   ⚠️  Warning: Fixture size > 10MB")

    print(f"\n✅ Fixtures created at: {fixture_dir}")
    print(f"   Commit to git for reproducible tests")

    return True


if __name__ == "__main__":
    success = extract_fixtures()
    exit(0 if success else 1)
