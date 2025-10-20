#!/usr/bin/env python3
"""
Scanshelf CLI - Minimal version for refactor

Available commands:
  add <pdf...>              Add book(s) to library
  process ocr <scan-id>     Run OCR stage
  process correct <scan-id> Run Correction stage
  status <scan-id>          Show pipeline status
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
            storage_root=Path.home() / "Documents" / "book_scans",
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

        elif args.stage == 'correct':
            # Import Correction stage
            correct_module = importlib.import_module('pipeline.2_correction')
            VisionCorrector = getattr(correct_module, 'VisionCorrector')

            # Clean Correction stage
            processor = VisionCorrector(
                storage_root=str(Path.home() / "Documents" / "book_scans")
            )
            processor.clean_stage(args.scan_id, confirm=args.yes)

        elif args.stage == 'label':
            # Import Label stage
            label_module = importlib.import_module('pipeline.3_label')
            VisionLabeler = getattr(label_module, 'VisionLabeler')

            # Clean Label stage
            processor = VisionLabeler(
                storage_root=str(Path.home() / "Documents" / "book_scans")
            )
            processor.clean_stage(args.scan_id, confirm=args.yes)

        elif args.stage == 'merge':
            # Import Merge stage
            merge_module = importlib.import_module('pipeline.4_merge')
            MergeProcessor = getattr(merge_module, 'MergeProcessor')

            # Clean Merge stage
            processor = MergeProcessor(
                storage_root=str(Path.home() / "Documents" / "book_scans")
            )
            processor.clean_stage(args.scan_id, confirm=args.yes)

        elif args.stage == 'structure':
            # Import Structure stage
            structure_module = importlib.import_module('pipeline.5_structure')
            clean_stage = getattr(structure_module, 'clean_stage')

            # Clean Structure stage
            storage_root = Path.home() / "Documents" / "book_scans"
            clean_stage(args.scan_id, storage_root, confirm=args.yes)

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
        VisionCorrector = getattr(correct_module, 'VisionCorrector')

        # Run Correction
        processor = VisionCorrector(
            storage_root=str(Path.home() / "Documents" / "book_scans"),
            model=args.model,
            max_workers=args.workers,
            max_retries=1 if getattr(args, 'no_retry', False) else 3
        )
        processor.process_book(args.scan_id, resume=args.resume)

        print(f"\n✅ Correction complete for {args.scan_id}")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def cmd_process_label(args):
    """Run Label stage (Stage 3)."""
    import importlib

    try:
        # Import Label stage
        label_module = importlib.import_module('pipeline.3_label')
        VisionLabeler = getattr(label_module, 'VisionLabeler')

        # Run Label
        processor = VisionLabeler(
            storage_root=str(Path.home() / "Documents" / "book_scans"),
            model=args.model,
            max_workers=args.workers,
            max_retries=1 if getattr(args, 'no_retry', False) else 3
        )
        processor.process_book(args.scan_id, resume=args.resume)

        print(f"\n✅ Label complete for {args.scan_id}")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def cmd_process_merge(args):
    """Run Merge & Enrich stage (Stage 4)."""
    import importlib

    try:
        # Import Merge stage
        merge_module = importlib.import_module('pipeline.4_merge')
        MergeProcessor = getattr(merge_module, 'MergeProcessor')

        # Run Merge
        processor = MergeProcessor(
            storage_root=str(Path.home() / "Documents" / "book_scans"),
            max_workers=args.workers
        )
        processor.process_book(args.scan_id, resume=args.resume)

        print(f"\n✅ Merge complete for {args.scan_id}")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def cmd_process_structure(args):
    """Run Structure Detection stage (Stage 5)."""
    import importlib

    try:
        # Import Structure stage
        structure_module = importlib.import_module('pipeline.5_structure')
        detect_structure = getattr(structure_module, 'detect_structure')

        from infra.checkpoint import CheckpointManager

        storage_root = Path.home() / "Documents" / "book_scans"
        book_dir = storage_root / args.scan_id

        # Initialize checkpoint
        checkpoint = CheckpointManager(
            scan_id=args.scan_id,
            stage="structure",
            storage_root=storage_root,
            output_dir="chapters"
        )

        if not args.resume:
            checkpoint.reset()

        # Run structure detection
        chapters_output = detect_structure(
            book_dir=book_dir,
            scan_id=args.scan_id,
            checkpoint_manager=checkpoint
        )

        print(f"\n✅ Structure detection complete for {args.scan_id}")
        print(f"   Chapters: {chapters_output.total_chapters}")
        print(f"   Cost: ${chapters_output.total_cost:.3f}")
        print(f"   Time: {chapters_output.processing_time_seconds:.1f}s")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def cmd_library_list(args):
    """List all books in library."""
    from tools.library import LibraryIndex
    from infra.checkpoint import CheckpointManager

    library = LibraryIndex(storage_root=Path.home() / "Documents" / "book_scans")
    scans = library.list_all_scans()

    if not scans:
        print("No books in library. Use 'ar add <pdf>' to add books.")
        return

    print(f"\n📚 Library ({len(scans)} books)\n")
    print(f"{'Scan ID':<30} {'Title':<35} {'Pipeline Status'}")
    print("-" * 95)

    storage_root = Path.home() / "Documents" / "book_scans"

    for scan in scans:
        scan_id = scan['scan_id']
        title = scan.get('title', 'Unknown')[:33]

        # Check checkpoint status for each stage
        stages = ['ocr', 'correction', 'labels', 'merge', 'structure']
        stage_symbols = []

        for stage in stages:
            checkpoint = CheckpointManager(
                scan_id=scan_id,
                stage=stage,
                storage_root=storage_root
            )
            status = checkpoint.get_status()
            stage_status = status.get('status', 'not_started')

            if stage_status == 'completed':
                stage_symbols.append('✅')
            elif stage_status == 'in_progress':
                # Check if actually complete (all pages done)
                total = status.get('total_pages', 0)
                completed = len(status.get('completed_pages', []))
                if total > 0 and completed == total:
                    stage_symbols.append('✅')  # Show as complete even if status says in_progress
                else:
                    stage_symbols.append('⏳')
            else:
                stage_symbols.append('○')

        # Format status string
        status_str = f"OCR:{stage_symbols[0]} COR:{stage_symbols[1]} LAB:{stage_symbols[2]} MRG:{stage_symbols[3]} STR:{stage_symbols[4]}"

        print(f"{scan_id:<30} {title:<35} {status_str}")


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


def cmd_library_delete(args):
    """Delete a book from the library."""
    from tools.library import LibraryIndex

    library = LibraryIndex(storage_root=Path.home() / "Documents" / "book_scans")

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
            scan_dir = Path.home() / "Documents" / "book_scans" / args.scan_id
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


def cmd_status(args):
    """Show pipeline status for a book."""
    from infra.checkpoint import CheckpointManager
    from datetime import datetime

    book_dir = Path.home() / "Documents" / "book_scans" / args.scan_id

    if not book_dir.exists():
        print(f"❌ Book not found: {args.scan_id}")
        sys.exit(1)

    # Load metadata
    metadata_file = book_dir / "metadata.json"
    if metadata_file.exists():
        import json
        with open(metadata_file) as f:
            metadata = json.load(f)
        title = metadata.get('title', args.scan_id)
    else:
        title = args.scan_id

    print(f"\n📊 Pipeline Status: {title}")
    print(f"   Scan ID: {args.scan_id}")
    print("=" * 70)
    print()

    # Track totals
    total_cost = 0.0
    total_duration = 0.0

    # Check OCR, Correction, and Merge stages
    stages = ['ocr', 'correction', 'merge']

    for stage in stages:
        checkpoint = CheckpointManager(
            scan_id=args.scan_id,
            stage=stage,
            storage_root=Path.home() / "Documents" / "book_scans"
        )

        status = checkpoint.get_status()
        stage_status = status.get('status', 'not_started')

        # Get metadata
        stage_metadata = status.get('metadata', {})
        cost = stage_metadata.get('total_cost_usd', 0.0) or stage_metadata.get('total_cost', 0.0)
        model = stage_metadata.get('model', None)

        # Calculate duration
        duration = None
        if stage_status == 'completed' and status.get('created_at') and status.get('completed_at'):
            try:
                start = datetime.fromisoformat(status['created_at'])
                end = datetime.fromisoformat(status['completed_at'])
                duration = (end - start).total_seconds()
            except:
                pass
        elif stage_status == 'in_progress' and status.get('created_at'):
            # For in-progress, calculate elapsed time from start to now
            try:
                start = datetime.fromisoformat(status['created_at'])
                duration = (datetime.now() - start).total_seconds()
            except:
                pass

        # Count progress from disk
        if stage == 'ocr':
            output_dir = book_dir / 'ocr'
        elif stage == 'correction':
            output_dir = book_dir / 'corrected'
        elif stage == 'merge':
            output_dir = book_dir / 'processed'
        else:
            output_dir = None

        progress_current = 0
        progress_total = status.get('total_pages', 0)

        if output_dir and output_dir.exists():
            progress_current = len(list(output_dir.glob('page_*.json')))

        # Display stage with columnar formatting
        display_name = stage.capitalize().ljust(10)

        if stage_status == 'not_started':
            icon = "○"
            print(f"{icon} {display_name} Not started")
        elif stage_status == 'completed':
            # Calculate failures
            total_pages = status.get('total_pages', 0)
            completed_pages = len(status.get('completed_pages', []))
            failed_pages = total_pages - completed_pages

            # Choose icon based on failures
            if failed_pages > 0:
                icon = "⚠️ "
                success_pct = (completed_pages / total_pages * 100) if total_pages > 0 else 100.0
                pct_str = f"{success_pct:.1f}%"
            else:
                icon = "✅"
                pct_str = "100.0%"

            duration_str = format_duration(duration) if duration else "N/A"
            cost_str = f"${cost:.2f}" if cost > 0 else "$0.00"

            # Columns: stage | % | time | cost
            status_line = f"{icon} {display_name} {pct_str:>6}  {duration_str:>8}  {cost_str:>7}"
            if failed_pages > 0:
                status_line += f"  ({failed_pages} failed)"
            print(status_line)

            total_cost += cost
            if duration:
                total_duration += duration
        else:  # in_progress
            icon = "⏳"
            if progress_total > 0:
                progress_pct = (progress_current / progress_total) * 100
                pct_str = f"{progress_pct:.1f}%"
                duration_str = format_duration(duration) if duration else "..."
                cost_str = f"${cost:.2f}" if cost > 0 else "$0.00"

                # Estimate time remaining
                eta_str = ""
                if duration and progress_current > 0:
                    rate = duration / progress_current  # seconds per page
                    remaining_pages = progress_total - progress_current
                    eta_seconds = rate * remaining_pages
                    eta_str = f"  ~{format_duration(eta_seconds)} left"

                # Columns: stage | % | time | cost | eta
                print(f"{icon} {display_name} {pct_str:>6}  {duration_str:>8}  {cost_str:>7}{eta_str}")

                # Add totals for in-progress stages
                if cost > 0:
                    total_cost += cost
                if duration:
                    total_duration += duration
            else:
                print(f"{icon} {display_name} In progress...")

    print()

    # Show totals
    if total_cost > 0:
        print(f"💰 Total Cost: ${total_cost:.2f}")
    if total_duration > 0:
        print(f"⏱️  Total Time: {format_duration(total_duration)}")

    if total_cost > 0 or total_duration > 0:
        print()

    print("=" * 70)


def format_duration(seconds):
    """Format duration in seconds to human-readable format."""
    if seconds is None or seconds < 0:
        return "N/A"

    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        mins = int(seconds / 60)
        secs = int(seconds % 60)
        return f"{mins}m {secs}s"
    else:
        hours = int(seconds / 3600)
        mins = int((seconds % 3600) / 60)
        return f"{hours}h {mins}m"


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
  ar status accidental-president
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
    ocr_parser.add_argument('--workers', type=int, default=None, help='Parallel workers (default: auto-detect CPU cores)')
    ocr_parser.add_argument('--resume', action='store_true', help='Resume from checkpoint')
    ocr_parser.set_defaults(func=cmd_process_ocr)

    # ar process correct
    correct_parser = process_subparsers.add_parser('correct', help='Stage 2: Correction (Vision)')
    correct_parser.add_argument('scan_id', help='Book scan ID')
    correct_parser.add_argument('--model', default=None, help='Vision model (default: from VISION_MODEL env var or qwen/qwen3-vl-235b-a22b-instruct)')
    correct_parser.add_argument('--workers', type=int, default=30, help='Parallel workers (default: 30)')
    correct_parser.add_argument('--resume', action='store_true', help='Resume from checkpoint')
    correct_parser.add_argument('--no-retry', action='store_true', help='Disable retries (for failure analysis)')
    correct_parser.set_defaults(func=cmd_process_correct)

    # ar process label
    label_parser = process_subparsers.add_parser('label', help='Stage 3: Label (Vision)')
    label_parser.add_argument('scan_id', help='Book scan ID')
    label_parser.add_argument('--model', default=None, help='Vision model (default: from VISION_MODEL env var or qwen/qwen3-vl-235b-a22b-instruct)')
    label_parser.add_argument('--workers', type=int, default=30, help='Parallel workers (default: 30)')
    label_parser.add_argument('--resume', action='store_true', help='Resume from checkpoint')
    label_parser.add_argument('--no-retry', action='store_true', help='Disable retries (for failure analysis)')
    label_parser.set_defaults(func=cmd_process_label)

    # ar process merge
    merge_parser = process_subparsers.add_parser('merge', help='Stage 4: Merge & Enrich')
    merge_parser.add_argument('scan_id', help='Book scan ID')
    merge_parser.add_argument('--workers', type=int, default=8, help='Parallel workers (default: 8)')
    merge_parser.add_argument('--resume', action='store_true', help='Resume from checkpoint')
    merge_parser.set_defaults(func=cmd_process_merge)

    # ar process structure
    structure_parser = process_subparsers.add_parser('structure', help='Stage 5: Structure Detection')
    structure_parser.add_argument('scan_id', help='Book scan ID')
    structure_parser.add_argument('--resume', action='store_true', help='Resume from checkpoint')
    structure_parser.set_defaults(func=cmd_process_structure)

    # ar process clean
    clean_parser = process_subparsers.add_parser('clean', help='Clean/delete stage outputs')
    clean_parser.add_argument('stage', choices=['ocr', 'correct', 'label', 'merge', 'structure'], help='Stage to clean')
    clean_parser.add_argument('scan_id', help='Book scan ID')
    clean_parser.add_argument('-y', '--yes', action='store_true', help='Skip confirmation prompt')
    clean_parser.set_defaults(func=cmd_process_clean)

    # ===== ar status =====
    status_parser = subparsers.add_parser('status', help='Show pipeline status')
    status_parser.add_argument('scan_id', help='Book scan ID')
    status_parser.set_defaults(func=cmd_status)

    # ===== ar library =====
    library_parser = subparsers.add_parser('library', help='Library management')
    library_subparsers = library_parser.add_subparsers(dest='library_command', help='Library command')
    library_subparsers.required = True

    # ar library add
    add_parser = library_subparsers.add_parser('add', help='Add book(s) to library')
    add_parser.add_argument('pdf_patterns', nargs='+', help='PDF file pattern(s) (e.g., accidental-president-*.pdf)')
    add_parser.add_argument('--run-ocr', action='store_true', help='Automatically run OCR stage after adding')
    add_parser.set_defaults(func=cmd_library_add)

    # ar library list
    list_parser = library_subparsers.add_parser('list', help='List all books')
    list_parser.set_defaults(func=cmd_library_list)

    # ar library show
    show_parser = library_subparsers.add_parser('show', help='Show book details')
    show_parser.add_argument('scan_id', help='Book scan ID')
    show_parser.set_defaults(func=cmd_library_show)

    # ar library delete
    delete_parser = library_subparsers.add_parser('delete', help='Delete book from library')
    delete_parser.add_argument('scan_id', help='Book scan ID')
    delete_parser.add_argument('-y', '--yes', action='store_true', help='Skip confirmation prompt')
    delete_parser.add_argument('--keep-files', action='store_true', help='Keep files on disk (only remove from library)')
    delete_parser.set_defaults(func=cmd_library_delete)

    # Parse and execute
    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
