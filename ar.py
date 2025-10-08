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
import os
import argparse
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))


def cmd_library_add(args):
    """Add book(s) to library with LLM metadata extraction."""
    from tools.add import add_books_to_library
    import glob

    # Expand glob pattern
    pdf_paths = []
    for pattern in args.pdf_patterns:
        matches = glob.glob(os.path.expanduser(pattern))
        if not matches:
            print(f"⚠️  No files match pattern: {pattern}")
        pdf_paths.extend([Path(p) for p in matches])

    if not pdf_paths:
        print("❌ No PDF files found")
        sys.exit(1)

    # Validate all paths exist and are PDFs
    for pdf_path in pdf_paths:
        if not pdf_path.exists():
            print(f"Error: File not found: {pdf_path}")
            sys.exit(1)
        if pdf_path.suffix.lower() != '.pdf':
            print(f"Error: Not a PDF file: {pdf_path}")
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
        import traceback
        traceback.print_exc()
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


def cmd_process_clean(args):
    """Clean a pipeline stage for a book."""
    import importlib

    try:
        if args.stage == 'ocr':
            # Import OCR stage
            ocr_module = importlib.import_module('pipeline.1_ocr')
            BookOCRProcessor = getattr(ocr_module, 'BookOCRProcessor')

            # Clean OCR stage
            processor = BookOCRProcessor(
                storage_root=str(Path.home() / "Documents" / "book_scans")
            )
            processor.clean_stage(args.scan_id, confirm=args.yes)

        else:
            print(f"❌ Clean not implemented for stage: {args.stage}")
            sys.exit(1)

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
    scans = library.list_all_scans()

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
    scan = library.get_scan_info(args.scan_id)

    if not scan:
        print(f"❌ Book not found: {args.scan_id}")
        sys.exit(1)

    print(f"\n📖 {scan['title']}")
    print("=" * 80)
    print(f"Scan ID:     {scan['scan']['scan_id']}")
    print(f"Author:      {scan.get('author', 'Unknown')}")
    print(f"Publisher:   {scan.get('publisher', 'Unknown')}")
    print(f"Year:        {scan.get('year', 'Unknown')}")
    print(f"Pages:       {scan['scan'].get('pages', 'Unknown')}")
    print(f"Status:      {scan['scan'].get('status', 'unknown')}")

    if scan['scan'].get('cost_usd'):
        print(f"Cost:        ${scan['scan']['cost_usd']:.2f}")

    if scan['scan'].get('models'):
        print(f"\nModels used:")
        for stage, model in scan['scan']['models'].items():
            print(f"  {stage}: {model}")

    print()


def main():
    parser = argparse.ArgumentParser(
        prog='ar',
        description='Scanshelf - Turn physical books into digital libraries',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  ar library add ~/Documents/Scans/accidental-president-*.pdf
  ar library list
  ar library show accidental-president
  ar process ocr accidental-president
  ar process ocr accidental-president --resume
  ar process clean ocr accidental-president
  ar process correct accidental-president --workers 30

Note: Minimal CLI during refactor (Issue #55).
      Commands will be added as stages are implemented (Issues #48-54).
"""
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    subparsers.required = True


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

    # ar process clean
    clean_parser = process_subparsers.add_parser('clean', help='Clean/delete stage outputs')
    clean_parser.add_argument('stage', choices=['ocr', 'correct'], help='Stage to clean')
    clean_parser.add_argument('scan_id', help='Book scan ID')
    clean_parser.add_argument('-y', '--yes', action='store_true', help='Skip confirmation prompt')
    clean_parser.set_defaults(func=cmd_process_clean)

    # ===== ar library =====
    library_parser = subparsers.add_parser('library', help='Library management')
    library_subparsers = library_parser.add_subparsers(dest='library_command', help='Library command')
    library_subparsers.required = True

    # ar library add
    add_parser = library_subparsers.add_parser('add', help='Add book(s) to library')
    add_parser.add_argument('pdf_patterns', nargs='+', help='PDF file pattern(s) (e.g., accidental-president-*.pdf)')
    add_parser.set_defaults(func=cmd_library_add)

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
