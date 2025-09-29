#!/usr/bin/env python3
"""
Scan Intake System - Step 1: Getting PDFs organized
Watches ScanSnap output and organizes by book title
"""

import os
import shutil
import json
from pathlib import Path
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import re


class BookScanOrganizer:
    """
    Simple system to:
    1. Watch ScanSnap output folder
    2. Move PDFs to organized structure
    3. Keep batches together (50-page scanner limit)
    4. Track book metadata
    """

    def __init__(self):
        # Default ScanSnap location on macOS
        self.watch_folder = Path("~/Documents/ScanSnap Home").expanduser()
        self.storage_root = Path("~/Documents/book_scans").expanduser()

        # Create base structure
        self.storage_root.mkdir(exist_ok=True)

        # Track current book being scanned
        self.current_book = None
        self.current_batch = 0

    def setup_book(self, book_title, author=None, isbn=None):
        """
        Call this when starting to scan a new book.
        Creates the folder structure for that book.
        """
        # Sanitize title for filesystem
        safe_title = re.sub(r'[^\w\s-]', '', book_title)
        safe_title = re.sub(r'[-\s]+', '-', safe_title)

        book_dir = self.storage_root / safe_title
        book_dir.mkdir(exist_ok=True)

        # Create subdirectories
        (book_dir / "raw_pdfs").mkdir(exist_ok=True)
        (book_dir / "batches").mkdir(exist_ok=True)

        # Save metadata
        metadata = {
            "title": book_title,
            "safe_title": safe_title,
            "author": author,
            "isbn": isbn,
            "scan_date": datetime.now().isoformat(),
            "batches": [],
            "total_pages": 0,
            "status": "scanning"
        }

        metadata_file = book_dir / "metadata.json"
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        # Set as current book
        self.current_book = safe_title
        self.current_batch = 0

        print(f"✓ Set up book: {book_title}")
        print(f"  Directory: {book_dir}")
        print(f"  Ready to receive scans...")

        return book_dir

    def intake_pdf(self, pdf_path, page_start=None, page_end=None):
        """
        Move a PDF from ScanSnap output to our organized structure.

        Args:
            pdf_path: Path to the PDF file
            page_start: Starting page number (e.g., 1, 51, 101)
            page_end: Ending page number (e.g., 50, 100, 150)
        """
        if not self.current_book:
            print("❌ No book set up! Call setup_book() first.")
            return None

        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            print(f"❌ File not found: {pdf_path}")
            return None

        book_dir = self.storage_root / self.current_book

        # Increment batch counter
        self.current_batch += 1

        # Create batch directory
        batch_dir = book_dir / "batches" / f"batch_{self.current_batch:03d}"
        batch_dir.mkdir(exist_ok=True)

        # Generate filename with page range
        if page_start and page_end:
            new_name = f"{self.current_book}_p{page_start:04d}-{page_end:04d}.pdf"
        else:
            new_name = f"{self.current_book}_batch{self.current_batch:03d}.pdf"

        # Copy to both locations
        # 1. To batches folder (for processing)
        batch_dest = batch_dir / new_name
        shutil.copy2(pdf_path, batch_dest)

        # 2. To raw_pdfs folder (for archive)
        raw_dest = book_dir / "raw_pdfs" / new_name
        shutil.copy2(pdf_path, raw_dest)

        # Update metadata
        metadata_file = book_dir / "metadata.json"
        with open(metadata_file, 'r') as f:
            metadata = json.load(f)

        batch_info = {
            "batch_number": self.current_batch,
            "filename": new_name,
            "page_start": page_start,
            "page_end": page_end,
            "timestamp": datetime.now().isoformat(),
            "original_path": str(pdf_path),
            "status": "pending"
        }

        metadata["batches"].append(batch_info)
        if page_start and page_end:
            metadata["total_pages"] = max(metadata["total_pages"], page_end)

        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        print(f"✓ Ingested: {new_name}")
        print(f"  → {batch_dest}")

        # Optionally delete original
        # pdf_path.unlink()

        return batch_dest

    def finish_book(self):
        """Call when done scanning a book."""
        if not self.current_book:
            print("No book currently being scanned.")
            return

        book_dir = self.storage_root / self.current_book
        metadata_file = book_dir / "metadata.json"

        with open(metadata_file, 'r') as f:
            metadata = json.load(f)

        metadata["status"] = "complete"
        metadata["completion_date"] = datetime.now().isoformat()

        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        print(f"✓ Book complete: {metadata['title']}")
        print(f"  Total batches: {len(metadata['batches'])}")
        print(f"  Estimated pages: {metadata['total_pages']}")

        self.current_book = None
        self.current_batch = 0

    def list_books(self):
        """Show all books in the system."""
        books = []
        for book_dir in self.storage_root.iterdir():
            if book_dir.is_dir():
                metadata_file = book_dir / "metadata.json"
                if metadata_file.exists():
                    with open(metadata_file) as f:
                        books.append(json.load(f))

        print("\n📚 Books in system:")
        for book in books:
            status_emoji = "✓" if book["status"] == "complete" else "⏳"
            print(f"{status_emoji} {book['title']}")
            print(f"   Author: {book.get('author', 'Unknown')}")
            print(f"   Batches: {len(book['batches'])}")
            print(f"   Pages: ~{book['total_pages']}")
            print(f"   Status: {book['status']}")
            print()

        return books


class ScanWatcher(FileSystemEventHandler):
    """
    Watches ScanSnap folder and auto-ingests PDFs.
    """

    def __init__(self, organizer):
        self.organizer = organizer

    def on_created(self, event):
        if event.src_path.endswith('.pdf'):
            print(f"\n🔍 Detected new scan: {event.src_path}")

            # Parse filename to get page range if possible
            filename = Path(event.src_path).name

            # Try to extract page numbers from filename
            # Assuming format like: scan_001-050.pdf or pages_51-100.pdf
            page_match = re.search(r'(\d+)[-_](\d+)', filename)

            if page_match:
                page_start = int(page_match.group(1))
                page_end = int(page_match.group(2))
                self.organizer.intake_pdf(event.src_path, page_start, page_end)
            else:
                # Ask for page range
                print("  ℹ️  Couldn't detect page range from filename")
                self.organizer.intake_pdf(event.src_path)


def interactive_mode():
    """
    Simple CLI for managing book scans.
    """
    organizer = BookScanOrganizer()

    print("📖 Book Scan Intake System")
    print("-" * 40)

    while True:
        print("\nCommands:")
        print("  1. Start new book")
        print("  2. Add PDF to current book")
        print("  3. Finish current book")
        print("  4. List all books")
        print("  5. Start watching folder")
        print("  6. Exit")

        choice = input("\nChoice: ").strip()

        if choice == "1":
            title = input("Book title: ").strip()
            author = input("Author (optional): ").strip() or None
            isbn = input("ISBN (optional): ").strip() or None
            organizer.setup_book(title, author, isbn)

        elif choice == "2":
            if not organizer.current_book:
                print("❌ No book active! Start a new book first.")
                continue

            pdf_path = input("PDF path (or drag file here): ").strip()
            # Remove quotes if dragged from Finder
            pdf_path = pdf_path.strip('"').strip("'")

            try:
                page_start = int(input("Starting page number: "))
                page_end = int(input("Ending page number: "))
            except:
                page_start = None
                page_end = None

            organizer.intake_pdf(pdf_path, page_start, page_end)

        elif choice == "3":
            organizer.finish_book()

        elif choice == "4":
            organizer.list_books()

        elif choice == "5":
            print("\n👁️  Starting folder watcher...")
            print(f"Watching: {organizer.watch_folder}")
            print("Press Ctrl+C to stop")

            event_handler = ScanWatcher(organizer)
            observer = Observer()
            observer.schedule(event_handler, str(organizer.watch_folder), recursive=True)
            observer.start()

            try:
                import time
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                observer.stop()
                print("\n✓ Watcher stopped")
            observer.join()

        elif choice == "6":
            break

        else:
            print("Invalid choice")

    print("\n👋 Goodbye!")


if __name__ == "__main__":
    # Quick test/demo mode
    interactive_mode()