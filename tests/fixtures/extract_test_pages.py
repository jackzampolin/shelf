#!/usr/bin/env python3
"""
Extract test pages from modest-lovelace for test fixtures.

This script extracts 5 challenging pages from the source PDFs to create
a small test dataset that exercises the full pipeline.
"""

import sys
from pathlib import Path
from PyPDF2 import PdfReader, PdfWriter

# Test pages: range from easy (1) to very challenging (5)
# Page 1: Title page (easy)
# Page 5: 0.00 confidence (very challenging)
# Page 109: 0.60 confidence, 5 errors
# Page 200: Mid-book, normal difficulty
# Page 384: 0.80 confidence, 6 errors
TEST_PAGES = [1, 5, 109, 200, 384]

# Map pages to source PDFs
BATCH_MAPPING = [
    (1, 77, "The-Accidental-President_p0001-0077.pdf"),
    (78, 176, "The-Accidental-President_p0078-0176.pdf"),
    (177, 274, "The-Accidental-President_p0177-0274.pdf"),
    (275, 372, "The-Accidental-President_p0275-0372.pdf"),
    (373, 447, "The-Accidental-President_p0373-0447.pdf"),
]


def extract_pages():
    """Extract test pages from source PDFs."""
    source_dir = Path.home() / "Documents" / "book_scans" / "modest-lovelace" / "source" / "pdfs"
    output_dir = Path(__file__).parent / "test_book" / "source"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Group pages by source PDF
    pages_by_pdf = {}
    for page in TEST_PAGES:
        for start, end, pdf_name in BATCH_MAPPING:
            if start <= page <= end:
                page_in_batch = page - start  # 0-indexed for PyPDF2
                if pdf_name not in pages_by_pdf:
                    pages_by_pdf[pdf_name] = []
                pages_by_pdf[pdf_name].append((page, page_in_batch))
                break

    # Extract pages from each source PDF
    for pdf_name, pages in pages_by_pdf.items():
        source_pdf = source_dir / pdf_name
        if not source_pdf.exists():
            print(f"Error: Source PDF not found: {source_pdf}")
            continue

        print(f"Extracting from {pdf_name}...")
        reader = PdfReader(source_pdf)

        for global_page, local_page in pages:
            # Create a single-page PDF for each test page
            output_pdf = output_dir / f"page_{global_page:04d}.pdf"

            writer = PdfWriter()
            writer.add_page(reader.pages[local_page])

            with open(output_pdf, 'wb') as f:
                writer.write(f)

            print(f"  Extracted page {global_page} -> {output_pdf.name}")

    print(f"\n✓ Extracted {len(TEST_PAGES)} test pages to {output_dir}")
    print("\nTest pages:")
    for page in TEST_PAGES:
        print(f"  - Page {page}")


if __name__ == "__main__":
    try:
        extract_pages()
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
