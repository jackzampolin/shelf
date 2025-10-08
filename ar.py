#!/usr/bin/env python3
"""
Scanshelf CLI - Minimal version for refactor

Available commands:
  add <pdf...>              Add book(s) to library
  process ocr <scan-id>     Run OCR stage
  process correct <scan-id> Run Correction stage
  library list              List all books
  library show <scan-id>    Show book details

Full CLI will be rebuilt as stages are implemented (Issues #48-54).
"""

import sys
import argparse
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))


def cmd_add(args):
    """Add book(s) to library with LLM metadata extraction."""
    from tools.ingest import add_books_to_library

    pdf_paths = [Path(p) for p in args.pdf_paths]

    # Validate all paths exist
    for pdf_path in pdf_paths:
        if not pdf_path.exists():
            print(f"Error: File not found: {pdf_path}")
            sys.exit(1)

    # Add to library
    try:
        result = add_books_to_library(
            pdf_paths=pdf_paths,
            storage_root=Path.home() / "Documents" / "book_scans"
        )

        print(f"\n✅ Added {result['books_added']} book(s) to library")
        for scan_id in result['scan_ids']:
            print(f"  - {scan_id}")

    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


def cmd_process_ocr(args):
    """Run OCR stage (Stage 1)."""
    import importlib

    try:
        # Import OCR stage
        ocr_module = importlib.import_module('pipeline.1_ocr')
        BookOCRProcessor = getattr(ocr_module, 'BookOCRProcessor')

        # Run OCR
        processor = BookOCRProcessor(
            storage_root=str(Path.home() / "Documents" / "book_scans"),
            max_workers=args.workers
        )
        processor.process_book(args.scan_id, resume=args.resume)

        print(f"\n✅ OCR complete for {args.scan_id}")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def cmd_process_correct(args):
    """Run Correction stage (Stage 2)."""
    import importlib

    try:
        # Import Correction stage
        correct_module = importlib.import_module('pipeline.2_correction')
        StructuredPageCorrector = getattr(correct_module, 'StructuredPageCorrector')

        # Run Correction
        processor = StructuredPageCorrector(
            book_slug=args.scan_id,
            storage_root=str(Path.home() / "Documents" / "book_scans"),
            model=args.model,
            max_workers=args.workers,
            calls_per_minute=args.rate_limit
        )
        processor.process_pages(resume=args.resume)

        print(f"\n✅ Correction complete for {args.scan_id}")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def cmd_library_list(args):
    """List all books in library."""
    from tools.library import LibraryIndex

    library = LibraryIndex(storage_root=Path.home() / "Documents" / "book_scans")
    scans = library.list_scans()

    if not scans:
        print("No books in library. Use 'ar add <pdf>' to add books.")
        return

    print(f"\n📚 Library ({len(scans)} books)\n")
    print(f"{'Scan ID':<30} {'Title':<40} {'Status'}")
    print("-" * 100)

    for scan in scans:
        scan_id = scan['scan_id']
        title = scan.get('title', 'Unknown')[:38]
        status = scan.get('status', 'unknown')
        print(f"{scan_id:<30} {title:<40} {status}")


def cmd_library_show(args):
    """Show detailed information about a book."""
    from tools.library import LibraryIndex
    import json

    library = LibraryIndex(storage_root=Path.home() / "Documents" / "book_scans")
    scan = library.get_scan(args.scan_id)

    if not scan:
        print(f"❌ Book not found: {args.scan_id}")
        sys.exit(1)

    print(f"\n📖 {scan.get('title', 'Unknown Title')}")
    print("=" * 80)
    print(f"Scan ID:     {scan['scan_id']}")
    print(f"Author:      {scan.get('author', 'Unknown')}")
    print(f"Publisher:   {scan.get('publisher', 'Unknown')}")
    print(f"Year:        {scan.get('publication_year', 'Unknown')}")
    print(f"Pages:       {scan.get('total_pages', 'Unknown')}")
    print(f"Status:      {scan.get('status', 'unknown')}")

    if scan.get('cost_usd'):
        print(f"Cost:        ${scan['cost_usd']:.2f}")

    if scan.get('models'):
        print(f"\nModels used:")
        for stage, model in scan['models'].items():
            print(f"  {stage}: {model}")

    print()


def main():
    parser = argparse.ArgumentParser(
        prog='ar',
        description='Scanshelf - Turn physical books into digital libraries',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  ar add ~/Documents/Scans/book.pdf
  ar process ocr modest-lovelace
  ar process correct modest-lovelace --workers 30
  ar library list
  ar library show modest-lovelace

Note: Minimal CLI during refactor (Issue #55).
      Commands will be added as stages are implemented (Issues #48-54).
"""
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    subparsers.required = True

    # ===== ar add =====
    add_parser = subparsers.add_parser('add', help='Add book(s) to library')
    add_parser.add_argument('pdf_paths', nargs='+', help='PDF file path(s)')
    add_parser.set_defaults(func=cmd_add)

    # ===== ar process =====
    process_parser = subparsers.add_parser('process', help='Run pipeline stages')
    process_subparsers = process_parser.add_subparsers(dest='stage', help='Stage to run')
    process_subparsers.required = True

    # ar process ocr
    ocr_parser = process_subparsers.add_parser('ocr', help='Stage 1: OCR')
    ocr_parser.add_argument('scan_id', help='Book scan ID')
    ocr_parser.add_argument('--workers', type=int, default=8, help='Parallel workers (default: 8)')
    ocr_parser.add_argument('--resume', action='store_true', help='Resume from checkpoint')
    ocr_parser.set_defaults(func=cmd_process_ocr)

    # ar process correct
    correct_parser = process_subparsers.add_parser('correct', help='Stage 2: Correction')
    correct_parser.add_argument('scan_id', help='Book scan ID')
    correct_parser.add_argument('--model', default='openai/gpt-4o-mini', help='LLM model (default: gpt-4o-mini)')
    correct_parser.add_argument('--workers', type=int, default=30, help='Parallel workers (default: 30)')
    correct_parser.add_argument('--rate-limit', type=int, default=150, help='API calls/min (default: 150)')
    correct_parser.add_argument('--resume', action='store_true', help='Resume from checkpoint')
    correct_parser.set_defaults(func=cmd_process_correct)

    # ===== ar library =====
    library_parser = subparsers.add_parser('library', help='Library management')
    library_subparsers = library_parser.add_subparsers(dest='library_command', help='Library command')
    library_subparsers.required = True

    # ar library list
    list_parser = library_subparsers.add_parser('list', help='List all books')
    list_parser.set_defaults(func=cmd_library_list)

    # ar library show
    show_parser = library_subparsers.add_parser('show', help='Show book details')
    show_parser.add_argument('scan_id', help='Book scan ID')
    show_parser.set_defaults(func=cmd_library_show)

    # Parse and execute
    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
