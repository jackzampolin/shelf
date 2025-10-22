#!/usr/bin/env python3
"""
Scanshelf CLI - Turn physical books into digital libraries

Commands:
  Library:
    shelf add <pdf...>           Add book(s) to library
    shelf list                   List all books
    shelf show <scan-id>         Show book details
    shelf status <scan-id>       Show pipeline status
    shelf stats                  Library statistics
    shelf delete <scan-id>       Delete book from library

  Pipeline:
    shelf process <scan-id>               Run full pipeline (auto-resume)
    shelf process <scan-id> --stage <s>   Run single stage
    shelf process <scan-id> --stages <s>  Run multiple stages

  Cleanup:
    shelf clean <scan-id> --stage <s>     Clean stage outputs
"""

import sys
import os
import argparse
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from infra.storage.library_storage import LibraryStorage
from infra.storage.book_storage import BookStorage
from infra.pipeline.runner import run_stage, run_pipeline
from infra.config import Config

# Import Stage classes
from pipeline.ocr import OCRStage
from pipeline.correction import CorrectionStage
from pipeline.label import LabelStage
from pipeline.merged import MergeStage


# ===== Library Commands =====

def cmd_library_add(args):
    """Add book(s) to library with LLM metadata extraction."""
    from tools.add import add_books_to_library
    import glob

    # Expand glob patterns
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
            print(f"❌ File not found: {pdf_path}")
            sys.exit(1)
        if pdf_path.suffix.lower() != '.pdf':
            print(f"❌ Not a PDF file: {pdf_path}")
            sys.exit(1)

    # Add to library
    try:
        result = add_books_to_library(
            pdf_paths=pdf_paths,
            storage_root=Config.BOOK_STORAGE_ROOT,
            run_ocr=args.run_ocr
        )

        print(f"\n✅ Added {result['books_added']} book(s) to library")
        for scan_id in result['scan_ids']:
            print(f"  - {scan_id}")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def cmd_library_list(args):
    """List all books in library."""
    library = LibraryStorage(storage_root=Config.BOOK_STORAGE_ROOT)
    scans = library.list_all_scans()

    if not scans:
        print("No books in library. Use 'shelf add <pdf>' to add books.")
        return

    print(f"\n📚 Library ({len(scans)} books)\n")
    print(f"{'Scan ID':<30} {'Title':<35} {'Pipeline Status'}")
    print("-" * 95)

    for scan in scans:
        scan_id = scan['scan_id']
        title = scan.get('title', 'Unknown')[:33]

        # Get stage status using BookStorage
        try:
            storage = library.get_book_storage(scan_id)
            stage_symbols = []

            for stage_name in ['ocr', 'corrected', 'labels', 'merged']:
                stage_storage = storage.stage(stage_name)
                checkpoint = stage_storage.checkpoint
                status = checkpoint.get_status()
                stage_status = status.get('status', 'not_started')

                if stage_status == 'completed':
                    stage_symbols.append('✅')
                elif stage_status == 'in_progress':
                    # Check if actually complete
                    total = status.get('total_pages', 0)
                    completed = len(status.get('completed_pages', []))
                    if total > 0 and completed == total:
                        stage_symbols.append('✅')
                    else:
                        stage_symbols.append('⏳')
                else:
                    stage_symbols.append('○')

            # Format status string
            status_str = f"OCR:{stage_symbols[0]} COR:{stage_symbols[1]} LAB:{stage_symbols[2]} MRG:{stage_symbols[3]}"

        except Exception:
            status_str = "ERROR"

        print(f"{scan_id:<30} {title:<35} {status_str}")


def cmd_library_show(args):
    """Show detailed information about a book."""
    library = LibraryStorage(storage_root=Config.BOOK_STORAGE_ROOT)
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


def cmd_library_status(args):
    """Show detailed pipeline status for a book."""
    library = LibraryStorage(storage_root=Config.BOOK_STORAGE_ROOT)

    # Verify book exists
    scan = library.get_scan_info(args.scan_id)
    if not scan:
        print(f"❌ Book not found: {args.scan_id}")
        sys.exit(1)

    print(f"\n📊 Pipeline Status: {args.scan_id}")
    print(f"Title: {scan['title']}")
    print("=" * 80)

    # Get storage
    storage = library.get_book_storage(args.scan_id)
    metadata = storage.load_metadata()
    total_pages = metadata.get('total_pages', 0)

    # Check each stage
    stages = [
        ('ocr', 'OCR'),
        ('corrected', 'Correction'),
        ('labels', 'Label'),
        ('merged', 'Merge')
    ]

    for stage_name, stage_label in stages:
        stage_storage = storage.stage(stage_name)
        checkpoint = stage_storage.checkpoint
        status = checkpoint.get_status()

        stage_status = status.get('status', 'not_started')
        completed_pages = len(status.get('completed_pages', []))

        # Status symbol
        if stage_status == 'completed':
            symbol = '✅'
        elif stage_status == 'in_progress':
            symbol = '⏳'
        elif stage_status == 'failed':
            symbol = '❌'
        else:
            symbol = '○'

        # Print stage info
        print(f"\n{symbol} {stage_label} ({stage_name})")
        print(f"   Status: {stage_status}")
        print(f"   Pages:  {completed_pages}/{total_pages}")

        if stage_status == 'completed':
            stage_metadata = status.get('metadata', {})
            if 'total_cost_usd' in stage_metadata:
                print(f"   Cost:   ${stage_metadata['total_cost_usd']:.3f}")

    print()


def cmd_library_stats(args):
    """Show library-wide statistics."""
    library = LibraryStorage(storage_root=Config.BOOK_STORAGE_ROOT)
    stats = library.get_stats()

    print(f"\n📊 Library Statistics")
    print("=" * 80)
    print(f"Total Books:  {stats['total_books']}")
    print(f"Total Scans:  {stats['total_scans']}")
    print(f"Total Pages:  {stats['total_pages']:,}")
    print(f"Total Cost:   ${stats['total_cost_usd']:.2f}")
    print()


def cmd_library_delete(args):
    """Delete a book from the library."""
    library = LibraryStorage(storage_root=Config.BOOK_STORAGE_ROOT)

    # Check if scan exists
    scan = library.get_scan_info(args.scan_id)
    if not scan:
        print(f"❌ Book not found: {args.scan_id}")
        sys.exit(1)

    # Confirm deletion unless --yes flag is used
    if not args.yes:
        print(f"\n⚠️  WARNING: This will delete:")
        print(f"   Scan ID: {args.scan_id}")
        print(f"   Title:   {scan['title']}")
        print(f"   Author:  {scan['author']}")

        if args.keep_files:
            print(f"\n   Library entry will be removed (files will be kept)")
        else:
            scan_dir = Config.BOOK_STORAGE_ROOT / args.scan_id
            print(f"\n   Library entry AND all files in: {scan_dir}")

        try:
            response = input("\nAre you sure? (yes/no): ").strip().lower()
            if response not in ['yes', 'y']:
                print("Cancelled.")
                sys.exit(0)
        except EOFError:
            print("\n❌ Cancelled (no input)")
            sys.exit(0)

    # Delete the scan
    try:
        result = library.delete_scan(
            scan_id=args.scan_id,
            delete_files=not args.keep_files,
            remove_empty_book=True
        )

        print(f"\n✅ Deleted: {result['scan_id']}")
        if result['files_deleted']:
            print(f"   Files deleted from: {result['scan_dir']}")
        if result['book_removed']:
            print(f"   Book '{result['book_slug']}' removed (no more scans)")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


# ===== Process Commands =====

def cmd_process(args):
    """Run pipeline stage(s) using runner.py."""
    library = LibraryStorage(storage_root=Config.BOOK_STORAGE_ROOT)

    # Verify book exists
    scan = library.get_scan_info(args.scan_id)
    if not scan:
        print(f"❌ Book not found: {args.scan_id}")
        sys.exit(1)

    # Get storage
    storage = library.get_book_storage(args.scan_id)

    # Determine which stages to run
    if args.stage:
        # Single stage
        stages_to_run = [args.stage]
    elif args.stages:
        # Multiple stages (comma-separated)
        stages_to_run = [s.strip() for s in args.stages.split(',')]
    else:
        # Full pipeline
        stages_to_run = ['ocr', 'corrected', 'labels', 'merged']

    # Map stage names to Stage instances
    stage_map = {
        'ocr': OCRStage(max_workers=args.workers),
        'corrected': CorrectionStage(
            model=args.model,
            max_workers=args.workers
        ),
        'labels': LabelStage(
            model=args.model,
            max_workers=args.workers
        ),
        'merged': MergeStage(max_workers=args.workers)
    }

    # Validate stage names
    for stage_name in stages_to_run:
        if stage_name not in stage_map:
            print(f"❌ Unknown stage: {stage_name}")
            print(f"   Valid stages: {', '.join(stage_map.keys())}")
            sys.exit(1)

    # Create stage instances
    stages = [stage_map[name] for name in stages_to_run]

    try:
        if len(stages) == 1:
            # Run single stage
            print(f"\n🔧 Running stage: {stages[0].name}")
            stats = run_stage(stages[0], storage, resume=True)
            print(f"\n✅ Stage complete: {stages[0].name}")
        else:
            # Run pipeline
            print(f"\n🔧 Running pipeline: {', '.join(s.name for s in stages)}")
            results = run_pipeline(stages, storage, resume=True, stop_on_error=True)
            print(f"\n✅ Pipeline complete: {len(results)} stages")

    except Exception as e:
        print(f"\n❌ Pipeline failed: {e}")
        sys.exit(1)


# ===== Clean Command =====

def cmd_clean(args):
    """Clean stage outputs for a book."""
    library = LibraryStorage(storage_root=Config.BOOK_STORAGE_ROOT)

    # Verify book exists
    scan = library.get_scan_info(args.scan_id)
    if not scan:
        print(f"❌ Book not found: {args.scan_id}")
        sys.exit(1)

    # Get storage
    storage = library.get_book_storage(args.scan_id)
    stage_storage = storage.stage(args.stage)

    # Confirm unless --yes flag
    if not args.yes:
        print(f"\n⚠️  WARNING: This will delete all outputs for:")
        print(f"   Book:  {args.scan_id}")
        print(f"   Stage: {args.stage}")
        print(f"   Path:  {stage_storage.output_dir}")

        try:
            response = input("\nAre you sure? (yes/no): ").strip().lower()
            if response not in ['yes', 'y']:
                print("Cancelled.")
                return
        except EOFError:
            print("\n❌ Cancelled (no input)")
            return

    # Clean stage
    try:
        checkpoint = stage_storage.checkpoint
        checkpoint.reset(confirm=False)  # Already confirmed above
        print(f"\n✅ Cleaned stage: {args.stage}")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


# ===== Main =====

def main():
    parser = argparse.ArgumentParser(
        prog='shelf',
        description='Scanshelf - Turn physical books into digital libraries',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  shelf add ~/Documents/Scans/book.pdf
  shelf list
  shelf show modest-lovelace
  shelf status modest-lovelace
  shelf process modest-lovelace
  shelf process modest-lovelace --stage ocr
  shelf process modest-lovelace --stages ocr,corrected
  shelf clean modest-lovelace --stage ocr
"""
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    subparsers.required = True

    # ===== Library Commands =====

    # shelf add
    add_parser = subparsers.add_parser('add', help='Add book(s) to library')
    add_parser.add_argument('pdf_patterns', nargs='+', help='PDF file pattern(s)')
    add_parser.add_argument('--run-ocr', action='store_true', help='Run OCR after adding')
    add_parser.set_defaults(func=cmd_library_add)

    # shelf list
    list_parser = subparsers.add_parser('list', help='List all books')
    list_parser.set_defaults(func=cmd_library_list)

    # shelf show
    show_parser = subparsers.add_parser('show', help='Show book details')
    show_parser.add_argument('scan_id', help='Book scan ID')
    show_parser.set_defaults(func=cmd_library_show)

    # shelf status
    status_parser = subparsers.add_parser('status', help='Show pipeline status')
    status_parser.add_argument('scan_id', help='Book scan ID')
    status_parser.set_defaults(func=cmd_library_status)

    # shelf stats
    stats_parser = subparsers.add_parser('stats', help='Library statistics')
    stats_parser.set_defaults(func=cmd_library_stats)

    # shelf delete
    delete_parser = subparsers.add_parser('delete', help='Delete book from library')
    delete_parser.add_argument('scan_id', help='Book scan ID')
    delete_parser.add_argument('-y', '--yes', action='store_true', help='Skip confirmation')
    delete_parser.add_argument('--keep-files', action='store_true', help='Keep files (only remove from library)')
    delete_parser.set_defaults(func=cmd_library_delete)

    # ===== Process Commands =====

    # shelf process
    process_parser = subparsers.add_parser('process', help='Run pipeline stages (auto-resume)')
    process_parser.add_argument('scan_id', help='Book scan ID')
    process_parser.add_argument('--stage', help='Single stage to run')
    process_parser.add_argument('--stages', help='Multiple stages (comma-separated)')
    process_parser.add_argument('--model', help='Vision model (for correction/label stages)')
    process_parser.add_argument('--workers', type=int, default=None, help='Parallel workers')
    process_parser.set_defaults(func=cmd_process)

    # ===== Clean Command =====

    # shelf clean
    clean_parser = subparsers.add_parser('clean', help='Clean stage outputs')
    clean_parser.add_argument('scan_id', help='Book scan ID')
    clean_parser.add_argument('--stage', required=True, choices=['ocr', 'corrected', 'labels', 'merged'], help='Stage to clean')
    clean_parser.add_argument('-y', '--yes', action='store_true', help='Skip confirmation')
    clean_parser.set_defaults(func=cmd_clean)

    # Parse and execute
    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
