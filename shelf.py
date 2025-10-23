#!/usr/bin/env python3
"""
Scanshelf CLI - Turn physical books into digital libraries

Commands:
  Library:
    shelf add <pdf...>           Add book(s) to library
    shelf list                   List all books
    shelf show <scan-id>         Show book details
    shelf status <scan-id>       Show pipeline status
    shelf report <scan-id> --stage <s>     Display stage report (CSV as table)
    shelf analyze <scan-id> --stage <s>    Analyze stage with AI agent
    shelf stats                  Library statistics
    shelf delete <scan-id>       Delete book from library

  Pipeline:
    shelf process <scan-id>                 Run full pipeline (auto-resume)
    shelf process <scan-id> --stage <s>     Run single stage
    shelf process <scan-id> --stages <s>    Run multiple stages
    shelf process <scan-id> --clean         Clean and re-run (start fresh)

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
    from infra.utils.ingest import add_books_to_library
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
            storage_root=Config.book_storage_root,
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
    library = LibraryStorage(storage_root=Config.book_storage_root)
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
    library = LibraryStorage(storage_root=Config.book_storage_root)
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

    print()


def cmd_library_status(args):
    """Show detailed pipeline status for a book."""
    library = LibraryStorage(storage_root=Config.book_storage_root)

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


def cmd_library_report(args):
    """Display stage report as a formatted table."""
    library = LibraryStorage(storage_root=Config.book_storage_root)

    # Verify book exists
    scan = library.get_scan_info(args.scan_id)
    if not scan:
        print(f"❌ Book not found: {args.scan_id}")
        sys.exit(1)

    # Get storage
    storage = library.get_book_storage(args.scan_id)
    stage_storage = storage.stage(args.stage)

    # Check if report exists
    report_file = stage_storage.output_dir / "report.csv"
    if not report_file.exists():
        print(f"❌ No report found for stage '{args.stage}'")
        print(f"   Expected: {report_file}")
        print(f"\n   Run the stage first to generate a report.")
        sys.exit(1)

    # Read CSV and display as table
    import csv
    from rich.console import Console
    from rich.table import Table

    console = Console()

    with open(report_file, 'r') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print(f"⚠️  Report is empty")
        return

    # Get limit (default: 20, show all if -a/--all flag)
    limit = None if args.all else (args.limit or 20)

    # Apply filters
    filtered_rows = rows
    if args.filter:
        # Parse filter: column=value or column>value or column<value
        filter_parts = args.filter.split('=')
        if len(filter_parts) == 2:
            col, val = filter_parts
            filtered_rows = [r for r in rows if r.get(col) == val]
        else:
            # Try numeric comparisons
            for op in ['>', '<', '>=', '<=']:
                if op in args.filter:
                    col, val = args.filter.split(op)
                    val = float(val)
                    if op == '>':
                        filtered_rows = [r for r in rows if float(r.get(col, 0)) > val]
                    elif op == '<':
                        filtered_rows = [r for r in rows if float(r.get(col, 0)) < val]
                    elif op == '>=':
                        filtered_rows = [r for r in rows if float(r.get(col, 0)) >= val]
                    elif op == '<=':
                        filtered_rows = [r for r in rows if float(r.get(col, 0)) <= val]
                    break

    # Create table
    table = Table(title=f"{args.scan_id} - {args.stage} report ({len(filtered_rows)} rows)")

    # Add columns
    columns = list(rows[0].keys())
    for col in columns:
        table.add_column(col, style="cyan" if col == "page_num" else None)

    # Add rows (with limit)
    display_rows = filtered_rows[:limit] if limit else filtered_rows
    for row in display_rows:
        table.add_row(*[row[col] for col in columns])

    # Show table
    console.print(table)

    # Show summary if limited
    if limit and len(filtered_rows) > limit:
        print(f"\nShowing {limit} of {len(filtered_rows)} rows. Use --all to show all rows.")


def cmd_library_stats(args):
    """Show library-wide statistics."""
    library = LibraryStorage(storage_root=Config.book_storage_root)
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
    library = LibraryStorage(storage_root=Config.book_storage_root)

    # Check if scan exists
    scan = library.get_scan_info(args.scan_id)
    if not scan:
        print(f"❌ Book not found: {args.scan_id}")
        sys.exit(1)

    # Confirm deletion unless --yes flag is used
    if not args.yes:
        print(f"\n⚠️  WARNING: This will delete:")
        print(f"   Scan ID: {args.scan_id}")
        print(f"   Title:   {scan.get('title', args.scan_id)}")
        print(f"   Author:  {scan.get('author', 'Unknown')}")

        if args.keep_files:
            print(f"\n   Library entry will be removed (files will be kept)")
        else:
            scan_dir = Config.book_storage_root / args.scan_id
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

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


# ===== Process Commands =====

def _clean_stage_helper(storage, stage_name):
    """
    Helper function to clean a stage's outputs.

    Args:
        storage: BookStorage instance
        stage_name: Name of the stage to clean
    """
    import shutil

    stage_storage = storage.stage(stage_name)

    # Delete all files in output directory except .gitkeep
    if stage_storage.output_dir.exists():
        for item in stage_storage.output_dir.iterdir():
            if item.name == '.gitkeep':
                continue
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)

    # Reset checkpoint
    checkpoint = stage_storage.checkpoint
    checkpoint.reset(confirm=False)


def cmd_analyze(args):
    """Analyze stage outputs with AI agent."""
    library = LibraryStorage(storage_root=Config.book_storage_root)

    # Verify book exists
    scan = library.get_scan_info(args.scan_id)
    if not scan:
        print(f"❌ Book not found: {args.scan_id}")
        sys.exit(1)

    # Get storage
    storage = library.get_book_storage(args.scan_id)

    # Check if stage has been run
    stage_storage = storage.stage(args.stage)
    report_path = stage_storage.output_dir / "report.csv"

    if not report_path.exists():
        print(f"❌ No report found for {args.stage} stage")
        print(f"   Run: shelf process {args.scan_id} --stage {args.stage}")
        sys.exit(1)

    # Map stage names to stage classes
    stage_classes = {
        'labels': LabelStage,
        'corrected': CorrectionStage,
    }

    stage_class = stage_classes[args.stage]

    print(f"\n🔍 Analyzing {args.stage} stage for {args.scan_id}...")
    if args.model:
        print(f"   Model: {args.model}")
    else:
        print(f"   Model: {Config.text_model_primary} (default)")

    if args.focus:
        print(f"   Focus areas: {', '.join(args.focus)}")

    try:
        # Launch analysis agent
        result = stage_class.analyze(
            storage=storage,
            model=args.model,
            focus_areas=args.focus
        )

        print(f"\n✅ Analysis complete!")
        print(f"   Report: {result['analysis_path']}")
        print(f"   Tool calls: {result['tool_calls_path']}")
        print(f"   Cost: ${result['cost_usd']:.4f}")
        print(f"   Iterations: {result['iterations']}")
        print(f"   Run hash: {result['run_hash']}")

    except Exception as e:
        print(f"\n❌ Analysis failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def cmd_process(args):
    """Run pipeline stage(s) using runner.py."""
    library = LibraryStorage(storage_root=Config.book_storage_root)

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
    # Auto-analyze enabled by default for correction and label stages
    auto_analyze = getattr(args, 'auto_analyze', True)

    stage_map = {
        'ocr': OCRStage(max_workers=args.workers if args.workers else None),
        'corrected': CorrectionStage(
            model=args.model,
            max_workers=args.workers if args.workers else 30,
            auto_analyze=auto_analyze
        ),
        'labels': LabelStage(
            model=args.model,
            max_workers=args.workers if args.workers else 30,
            auto_analyze=auto_analyze
        ),
        'merged': MergeStage(max_workers=args.workers if args.workers else 8)
    }

    # Validate stage names
    for stage_name in stages_to_run:
        if stage_name not in stage_map:
            print(f"❌ Unknown stage: {stage_name}")
            print(f"   Valid stages: {', '.join(stage_map.keys())}")
            sys.exit(1)

    # Clean stages if --clean flag is set
    if args.clean:
        print(f"\n🧹 Cleaning stages before processing: {', '.join(stages_to_run)}")
        for stage_name in stages_to_run:
            _clean_stage_helper(storage, stage_name)
            print(f"   ✓ Cleaned {stage_name}")
        print()

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
    library = LibraryStorage(storage_root=Config.book_storage_root)

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
        import shutil

        # Delete all files in output directory except keep .gitkeep if present
        if stage_storage.output_dir.exists():
            for item in stage_storage.output_dir.iterdir():
                if item.name == '.gitkeep':
                    continue
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)

        # Reset checkpoint
        checkpoint = stage_storage.checkpoint
        checkpoint.reset(confirm=False)

        print(f"\n✅ Cleaned stage: {args.stage}")
        print(f"   Deleted all outputs from: {stage_storage.output_dir}")
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
  shelf report modest-lovelace --stage corrected
  shelf report modest-lovelace --stage labels --filter "printed_page_number="
  shelf analyze modest-lovelace --stage labels
  shelf analyze modest-lovelace --stage corrected --focus corrections accuracy
  shelf process modest-lovelace
  shelf process modest-lovelace --stage ocr
  shelf process modest-lovelace --stages ocr,corrected
  shelf process modest-lovelace --stage labels --clean
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

    # shelf report
    report_parser = subparsers.add_parser('report', help='Display stage report as table')
    report_parser.add_argument('scan_id', help='Book scan ID')
    report_parser.add_argument('--stage', required=True, choices=['ocr', 'corrected', 'labels'], help='Stage to show report for')
    report_parser.add_argument('--limit', type=int, help='Number of rows to show (default: 20)')
    report_parser.add_argument('--all', '-a', action='store_true', help='Show all rows')
    report_parser.add_argument('--filter', help='Filter rows (e.g., "total_corrections>0")')
    report_parser.set_defaults(func=cmd_library_report)

    # shelf analyze
    analyze_parser = subparsers.add_parser('analyze', help='Analyze stage outputs with AI agent')
    analyze_parser.add_argument('scan_id', help='Book scan ID')
    analyze_parser.add_argument('--stage', required=True, choices=['labels', 'corrected'], help='Stage to analyze')
    analyze_parser.add_argument('--model', help='OpenRouter model (default: Config.text_model_primary)')
    analyze_parser.add_argument('--focus', nargs='+', help='Focus areas (e.g., page_numbers regions)')
    analyze_parser.set_defaults(func=cmd_analyze)

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
    process_parser.add_argument('--clean', action='store_true', help='Clean stages before processing (start fresh)')
    process_parser.add_argument('--no-auto-analyze', action='store_false', dest='auto_analyze', help='Disable automatic stage analysis (enabled by default)')
    process_parser.set_defaults(func=cmd_process, auto_analyze=True)

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
