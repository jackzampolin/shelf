#!/usr/bin/env python3
"""
Book OCR Processor - Step 2: Extract text from scanned PDFs
Converts PDFs to images and extracts text per page using Tesseract
"""

import json
from pathlib import Path
from pdf2image import convert_from_path
import pytesseract
from datetime import datetime


class BookOCRProcessor:
    """
    Processes scanned book PDFs to extract text on a per-page basis.
    """

    def __init__(self, storage_root=None):
        self.storage_root = Path(storage_root or "~/Documents/book_scans").expanduser()

    def process_book(self, book_title):
        """
        Process all batches for a given book.

        Args:
            book_title: Safe title of the book (e.g., "The-Accidental-President")
        """
        book_dir = self.storage_root / book_title

        if not book_dir.exists():
            print(f"❌ Book directory not found: {book_dir}")
            return

        # Load metadata
        metadata_file = book_dir / "metadata.json"
        with open(metadata_file, 'r') as f:
            metadata = json.load(f)

        print(f"📖 Processing: {metadata['title']}")
        print(f"   Total batches: {len(metadata['batches'])}")
        print(f"   Estimated pages: {metadata['total_pages']}")
        print()

        # Create OCR output directory
        ocr_dir = book_dir / "ocr_text"
        ocr_dir.mkdir(exist_ok=True)

        # Process each batch
        total_pages = 0
        for batch_info in metadata['batches']:
            batch_num = batch_info['batch_number']
            pdf_path = book_dir / "batches" / f"batch_{batch_num:03d}" / batch_info['filename']

            if not pdf_path.exists():
                print(f"⚠️  Batch {batch_num} PDF not found: {pdf_path}")
                continue

            pages_processed = self.process_batch(
                pdf_path,
                batch_num,
                ocr_dir,
                batch_info['page_start'],
                batch_info['page_end']
            )
            total_pages += pages_processed

            # Update batch status in metadata
            batch_info['ocr_status'] = 'complete'
            batch_info['ocr_timestamp'] = datetime.now().isoformat()

        # Update metadata
        metadata['ocr_complete'] = True
        metadata['ocr_completion_date'] = datetime.now().isoformat()
        metadata['total_pages_processed'] = total_pages

        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        print(f"\n✅ OCR complete: {total_pages} pages processed")

    def process_batch(self, pdf_path, batch_num, ocr_dir, page_start, page_end):
        """
        Process a single PDF batch, extracting text for each page.

        Args:
            pdf_path: Path to the PDF file
            batch_num: Batch number (for organization)
            ocr_dir: Root directory for OCR output
            page_start: Starting page number in book
            page_end: Ending page number in book

        Returns:
            Number of pages processed
        """
        print(f"📄 Batch {batch_num}: {pdf_path.name}")
        print(f"   Converting PDF to images...")

        # Create batch subdirectory
        batch_ocr_dir = ocr_dir / f"batch_{batch_num:03d}"
        batch_ocr_dir.mkdir(exist_ok=True)

        # Convert PDF to images
        try:
            images = convert_from_path(pdf_path, dpi=300)
        except Exception as e:
            print(f"❌ Error converting PDF: {e}")
            return 0

        num_pages = len(images)
        print(f"   Processing {num_pages} pages...")

        # Process each page
        for i, image in enumerate(images, start=1):
            # Calculate actual book page number
            book_page = page_start + i - 1

            # Progress indicator
            print(f"   Page {book_page:4d} ({i:2d}/{num_pages})...", end='', flush=True)

            try:
                # Extract text using Tesseract
                text = pytesseract.image_to_string(image, lang='eng')

                # Save text file
                text_file = batch_ocr_dir / f"page_{book_page:04d}.txt"
                with open(text_file, 'w', encoding='utf-8') as f:
                    f.write(f"# Page {book_page}\n")
                    f.write(f"# Batch {batch_num}\n")
                    f.write(f"# OCR Date: {datetime.now().isoformat()}\n\n")
                    f.write(text)

                print(f" ✓ ({len(text)} chars)")

            except Exception as e:
                print(f" ❌ Error: {e}")
                continue

        print(f"   ✅ Batch {batch_num} complete: {num_pages} pages\n")
        return num_pages

    def list_books(self):
        """List all books available for OCR processing."""
        books = []
        for book_dir in self.storage_root.iterdir():
            if book_dir.is_dir():
                metadata_file = book_dir / "metadata.json"
                if metadata_file.exists():
                    with open(metadata_file) as f:
                        metadata = json.load(f)
                        books.append(metadata)

        print("\n📚 Books available for OCR:")
        for book in books:
            ocr_status = "✅ Complete" if book.get('ocr_complete') else "⏳ Pending"
            print(f"{ocr_status} {book['title']}")
            print(f"         {len(book['batches'])} batches, ~{book['total_pages']} pages")
            if book.get('ocr_complete'):
                print(f"         Processed: {book.get('total_pages_processed', 0)} pages")
            print()

        return books


def interactive_mode():
    """
    Simple CLI for OCR processing.
    """
    processor = BookOCRProcessor()

    print("🔍 Book OCR Processor")
    print("-" * 40)

    while True:
        print("\nCommands:")
        print("  1. List books")
        print("  2. Process a book")
        print("  3. Exit")

        choice = input("\nChoice: ").strip()

        if choice == "1":
            processor.list_books()

        elif choice == "2":
            books = processor.list_books()
            book_title = input("\nEnter book safe title (e.g., 'The-Accidental-President'): ").strip()

            if book_title:
                processor.process_book(book_title)
            else:
                print("❌ No book title provided")

        elif choice == "3":
            break

        else:
            print("Invalid choice")

    print("\n👋 Done!")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        # Command-line mode
        processor = BookOCRProcessor()
        processor.process_book(sys.argv[1])
    else:
        # Interactive mode
        interactive_mode()