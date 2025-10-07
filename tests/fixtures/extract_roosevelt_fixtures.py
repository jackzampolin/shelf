#!/usr/bin/env python3
"""
Extract Roosevelt test fixtures from full book scan.

Creates a committed test dataset with:
- OCR JSON (5 pages)
- Corrected JSON (5 pages)
- Needs review JSON (3 pages for fix stage tests)
- Structured extraction (3 batches for structure tests)
- Structured metadata

Selected pages:
- page_0010: Early chapter, normal text
- page_0050: Mid-book, typical content
- page_0100: Later content
- page_0200: Deep in book
- page_0500: Near end

Needs review samples:
- page_0015: Early book (fix stage testing)
- page_0250: Mid book (fix stage testing)
- page_0475: Late book (fix stage testing)

Total size: ~200KB (acceptable for git)
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
    review_pages = [15, 250, 475]  # For fix stage tests
    extraction_batches = [0, 3, 7]  # Early, mid, late extraction batches

    # Copy metadata
    metadata_src = roosevelt_dir / "metadata.json"
    if metadata_src.exists():
        with open(metadata_src) as f:
            metadata = json.load(f)

        # Update for fixture
        metadata['fixture'] = True
        metadata['test_pages'] = test_pages
        metadata['review_pages'] = review_pages
        metadata['extraction_batches'] = extraction_batches

        with open(fixture_dir / "metadata.json", 'w') as f:
            json.dump(metadata, f, indent=2)
        print(f"✅ Copied metadata")

    # Create subdirectories
    for subdir in ['ocr', 'corrected', 'needs_review', 'structured']:
        (fixture_dir / subdir).mkdir()
    (fixture_dir / "structured" / "extraction").mkdir()

    # Extract pages
    extracted = {
        'ocr': 0,
        'corrected': 0,
        'needs_review': 0,
        'extraction': 0,
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

    # Extract needs_review pages (for fix stage tests)
    for page_num in review_pages:
        page_filename = f"page_{page_num:04d}.json"
        review_src = roosevelt_dir / "needs_review" / page_filename
        if review_src.exists():
            shutil.copy(review_src, fixture_dir / "needs_review" / page_filename)
            extracted['needs_review'] += 1

    # Extract structured extraction batches (for structure tests)
    structured_src = roosevelt_dir / "structured"
    if structured_src.exists():
        extraction_src = structured_src / "extraction"
        if extraction_src.exists():
            for batch_num in extraction_batches:
                batch_filename = f"batch_{batch_num:03d}.json"
                batch_src = extraction_src / batch_filename
                if batch_src.exists():
                    shutil.copy(batch_src, fixture_dir / "structured" / "extraction" / batch_filename)
                    extracted['extraction'] += 1

            # Copy extraction metadata
            extraction_meta = extraction_src / "metadata.json"
            if extraction_meta.exists():
                shutil.copy(extraction_meta, fixture_dir / "structured" / "extraction" / "metadata.json")

        # Copy structured metadata
        struct_meta = structured_src / "metadata.json"
        if struct_meta.exists():
            shutil.copy(struct_meta, fixture_dir / "structured" / "metadata.json")
            extracted['structured'] = 1

    print(f"\n📊 Extraction Summary:")
    print(f"   OCR pages: {extracted['ocr']}")
    print(f"   Corrected pages: {extracted['corrected']}")
    print(f"   Needs review pages: {extracted['needs_review']}")
    print(f"   Extraction batches: {extracted['extraction']}")
    print(f"   Structured files: {extracted['structured']}")

    # Calculate size
    total_size = sum(
        f.stat().st_size
        for f in fixture_dir.rglob('*')
        if f.is_file()
    )
    print(f"   Total size: {total_size / 1024:.1f} KB")

    if total_size > 500 * 1024:  # 500KB
        print(f"   ⚠️  Warning: Fixture size > 500KB")
        print(f"   Consider reducing fixture count")

    print(f"\n✅ Fixtures created at: {fixture_dir}")
    print(f"   Commit to git for reproducible tests")

    return True


if __name__ == "__main__":
    success = extract_fixtures()
    exit(0 if success else 1)
