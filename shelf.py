#!/usr/bin/env python3
"""
Scanshelf CLI - Turn physical books into digital libraries

Commands:
  Library Management:
    shelf shelve <pdf...>        Shelve book(s) into library
    shelf list                   List all books
    shelf show <scan-id>         Show book details
    shelf stats                  Library statistics
    shelf delete <scan-id>       Delete book from library

  Single Book Operations:
    shelf process <scan-id>                Run full pipeline (auto-resume)
    shelf process <scan-id> --stage <s>    Run single stage
    shelf status <scan-id>                 Show pipeline status
    shelf report <scan-id> --stage <s>     Display stage report (CSV as table)
    shelf analyze <scan-id> --stage <s>    Analyze stage with AI agent
    shelf clean <scan-id> --stage <s>      Clean stage outputs

  Library-wide Sweeps:
    shelf sweep <stage>          Sweep stage across all books (persistent random order)
    shelf sweep reports          Regenerate reports from checkpoints (no LLM calls)
"""

import sys
import os
import argparse
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from infra.storage.library import Library
from infra.storage.book_storage import BookStorage
from infra.pipeline.runner import run_stage, run_pipeline
from infra.config import Config

# Import Stage classes
from pipeline.ocr import OCRStage
from pipeline.ocr_v2 import OCRStageV2
from pipeline.correction import CorrectionStage
from pipeline.label import LabelStage
from pipeline.merged import MergeStage
from pipeline.build_structure import BuildStructureStage


# ===== Library Commands =====

def cmd_shelve(args):
    """Shelve book(s) into library with LLM metadata extraction."""
    from infra.storage.library import Library
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

    # Add to library (automatically updates all shuffle orders)
    try:
        library = Library(storage_root=Config.book_storage_root)
        result = library.add_books(
            pdf_paths=pdf_paths,
            run_ocr=args.run_ocr
        )

        print(f"\n✅ Added {result['books_added']} book(s) to library")
        for scan_id in result['scan_ids']:
            print(f"  - {scan_id}")

        # Show shuffle update info if shuffle exists
        if library.has_shuffle():
            print(f"   📚 Updated global shuffle order")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def cmd_library_list(args):
    """List all books in library."""
    library = Library(storage_root=Config.book_storage_root)
    scans = library.list_all_scans()

    if not scans:
        print("No books in library. Use 'shelf shelve <pdf>' to shelve books.")
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
    library = Library(storage_root=Config.book_storage_root)
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
    library = Library(storage_root=Config.book_storage_root)

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
        ('ocr_v2', 'OCR v2'),
        ('corrected', 'Correction'),
        ('labels', 'Label'),
        ('merged', 'Merge')
    ]

    for stage_name, stage_label in stages:
        stage_storage = storage.stage(stage_name)
        checkpoint = stage_storage.checkpoint
        status = checkpoint.get_status()

        stage_status = status.get('status', 'not_started')
        remaining_pages = len(status.get('remaining_pages', []))
        completed_pages = total_pages - remaining_pages

        # Status symbol
        if stage_status == 'completed':
            symbol = '✅'
        elif stage_status in ['not_started']:
            symbol = '○'
        elif stage_status == 'failed':
            symbol = '❌'
        else:
            # In-progress or checkpoint-specific phase (running-ocr, etc.)
            symbol = '⏳'

        # Print stage info
        print(f"\n{symbol} {stage_label} ({stage_name})")
        print(f"   Status: {stage_status}")
        print(f"   Pages:  {completed_pages}/{total_pages} ({remaining_pages} remaining)")

        # Show metrics for completed or in-progress stages
        stage_metrics = status.get('metrics', {})
        if stage_metrics.get('total_cost_usd', 0) > 0:
            print(f"   Cost:   ${stage_metrics['total_cost_usd']:.4f}")

        if stage_metrics.get('total_time_seconds', 0) > 0:
            mins = stage_metrics['total_time_seconds'] / 60
            print(f"   Time:   {mins:.1f}m")

        # OCR v2 specific details
        if stage_name == 'ocr_v2' and stage_status not in ['not_started', 'completed']:
            providers = status.get('providers', {})
            if providers:
                print(f"   Providers:")
                for pname, premaining in providers.items():
                    pcompleted = total_pages - len(premaining)
                    print(f"      {pname}: {pcompleted}/{total_pages} ({len(premaining)} remaining)")

            selection = status.get('selection', {})
            if selection:
                auto = selection.get('auto_selected', 0)
                vision = selection.get('vision_selected', 0)
                if auto > 0 or vision > 0:
                    print(f"   Selection: {auto} auto, {vision} vision")
                    if stage_metrics.get('vision_cost_usd', 0) > 0:
                        print(f"      Vision cost: ${stage_metrics['vision_cost_usd']:.4f}")

    print()


def cmd_stage_status(args):
    """Show detailed status for a specific stage (for debugging)."""
    library = Library(storage_root=Config.book_storage_root)

    # Verify book exists
    scan = library.get_scan_info(args.scan_id)
    if not scan:
        print(f"❌ Book not found: {args.scan_id}")
        sys.exit(1)

    storage = library.get_book_storage(args.scan_id)

    # Get stage instance
    stage_map = {
        'ocr': OCRStage(),
        'ocr_v2': OCRStageV2(),
        'corrected': CorrectionStage(),
        'labels': LabelStage(),
        'merged': MergeStage(),
    }

    if args.stage not in stage_map:
        print(f"❌ Unknown stage: {args.stage}")
        print(f"Available stages: {', '.join(stage_map.keys())}")
        sys.exit(1)

    stage = stage_map[args.stage]
    checkpoint = storage.stage(args.stage).checkpoint

    # Import logger
    from infra.pipeline.logger import PipelineLogger
    logger = PipelineLogger(storage.book_dir, args.stage)

    # Get progress structure
    progress = stage.get_progress(storage, checkpoint, logger)

    # Print as formatted JSON
    import json
    print(f"\n📊 Stage Status: {args.scan_id} / {args.stage}")
    print("=" * 80)
    print(json.dumps(progress, indent=2))
    print()


def cmd_library_report(args):
    """Display stage report as a formatted table."""
    library = Library(storage_root=Config.book_storage_root)

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
    library = Library(storage_root=Config.book_storage_root)
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
    from infra.storage.library import Library

    library = Library(storage_root=Config.book_storage_root)

    # Check if scan exists
    scan = library.get_book_info(args.scan_id)
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

    # Delete the scan (automatically updates all shuffle orders)
    try:
        result = library.delete_book(
            scan_id=args.scan_id,
            delete_files=not args.keep_files,
            remove_empty_book=True
        )

        print(f"\n✅ Deleted: {result['scan_id']}")
        if result['files_deleted']:
            print(f"   Files deleted from: {result['scan_dir']}")

        # Show shuffle update info if shuffle exists
        if library.has_shuffle():
            print(f"   📚 Removed from global shuffle order")

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
    library = Library(storage_root=Config.book_storage_root)

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
    library = Library(storage_root=Config.book_storage_root)

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
    # Auto-analyze disabled by default for correction and label stages (use --auto-analyze to enable)
    auto_analyze = getattr(args, 'auto_analyze', False)

    stage_map = {
        'ocr': OCRStage(max_workers=args.workers if args.workers else None),
        'ocr_v2': OCRStageV2(max_workers=args.workers if args.workers else None),
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
        'merged': MergeStage(max_workers=args.workers if args.workers else 8),
        'build_structure': BuildStructureStage(model=args.model)
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
    library = Library(storage_root=Config.book_storage_root)

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


def _sweep_stage(library, all_books, args):
    """Sweep a pipeline stage across all books in randomized order."""
    import shutil

    # Get or create global shuffle order (Library handles all the logic)
    scan_ids = library.create_shuffle(reshuffle=args.reshuffle)

    # Provide user feedback about shuffle state
    shuffle_info = library.get_shuffle_info()

    if args.reshuffle:
        print(f"🔀 Created new global shuffle order")
    elif shuffle_info:
        created_date = shuffle_info.get('created_at', '')[:10] if 'created_at' in shuffle_info else 'unknown'
        print(f"♻️  Using existing global shuffle order (created: {created_date})")
    else:
        print(f"🎲 Created random order")

    print(f"\n🧹 Sweeping '{args.target}' stage across {len(scan_ids)} books")
    print(f"   Press Ctrl+C to stop at any time")
    print(f"   Tip: Use --reshuffle to create a new random order\n")

    # Phase 1: Determine which books need processing (and clean if --force)
    books_to_process = []
    skipped_count = 0

    if args.force:
        print("Phase 1: Checking status and cleaning...")
    else:
        print("Phase 1: Checking status (resume mode)...")
    for idx, scan_id in enumerate(scan_ids, 1):
        try:
            storage = library.get_book_storage(scan_id)
            stage_storage = storage.stage(args.target)
            checkpoint = stage_storage.checkpoint

            # Check if already completed (unless --force flag)
            if not args.force:
                status = checkpoint.get_status()
                if status.get('status') == 'completed':
                    print(f"  [{idx}/{len(scan_ids)}] ⏭️  {scan_id}: Already completed - skipping")
                    skipped_count += 1
                    continue

            # Only clean if --force flag is set
            if args.force:
                print(f"  [{idx}/{len(scan_ids)}] 🧹 {scan_id}: Cleaning {args.target} stage...")
                if stage_storage.output_dir.exists():
                    for item in stage_storage.output_dir.iterdir():
                        if item.name == '.gitkeep':
                            continue
                        if item.is_file():
                            item.unlink()
                        elif item.is_dir():
                            shutil.rmtree(item)

                # Reset checkpoint
                checkpoint.reset(confirm=False)
            else:
                # Resume from checkpoint - check if in progress
                status = checkpoint.get_status()
                if status.get('status') == 'in_progress':
                    completed_pages = len(status.get('completed_pages', []))
                    total_pages = status.get('total_pages', 0)
                    print(f"  [{idx}/{len(scan_ids)}] ▶️  {scan_id}: Resuming ({completed_pages}/{total_pages} complete)")
                else:
                    print(f"  [{idx}/{len(scan_ids)}] ▶️  {scan_id}: Will process")

            # Add to process list
            books_to_process.append(scan_id)

        except KeyboardInterrupt:
            print(f"\n\n⚠️  Interrupted during Phase 1")
            print(f"   Queued: {len(books_to_process)}, Skipped: {skipped_count}, Remaining: {len(scan_ids) - idx}")
            if args.force:
                print(f"   Note: {len(books_to_process)} books were cleaned and need processing")
            sys.exit(0)
        except Exception as e:
            print(f"  [{idx}/{len(scan_ids)}] ❌ {scan_id}: Error during Phase 1: {e}")
            continue

    if args.force:
        print(f"\nPhase 1 complete: Cleaned {len(books_to_process)} books, skipped {skipped_count}")
    else:
        print(f"\nPhase 1 complete: {len(books_to_process)} books to process, {skipped_count} skipped")

    if not books_to_process:
        print("\n✅ No books to process")
        return

    # Phase 2: Run the stage on all cleaned books
    print(f"\nPhase 2: Running {args.target} stage on {len(books_to_process)} books...\n")
    processed_count = 0

    for idx, scan_id in enumerate(books_to_process, 1):
        print(f"\n{'='*60}")
        print(f"[{idx}/{len(books_to_process)}] Processing: {scan_id}")
        print(f"{'='*60}")

        try:
            storage = library.get_book_storage(scan_id)

            # Run stage (reuse cmd_process logic)
            print(f"  ▶️  Running {args.target} stage...")

            # Build args for process command
            process_args = argparse.Namespace(
                scan_id=scan_id,
                stage=args.target,
                stages=None,
                model=getattr(args, 'model', None),
                workers=getattr(args, 'workers', None),
                clean=False,  # Already cleaned in Phase 1
                auto_analyze=False,  # Disabled by default
            )

            # Run process
            cmd_process(process_args)

            print(f"  ✅ Completed: {scan_id}")
            processed_count += 1

        except KeyboardInterrupt:
            print(f"\n\n⚠️  Interrupted by user. Stopping...")
            print(f"   Processed: {processed_count}, Skipped: {skipped_count}, Remaining: {len(books_to_process) - idx}")
            print(f"   Note: Run without --force to continue from where you left off")
            sys.exit(0)
        except Exception as e:
            print(f"  ❌ Error processing {scan_id}: {e}")
            print(f"     Continuing to next book...")
            continue

    print(f"\n{'='*60}")
    print(f"✅ Sweep complete:")
    print(f"   Processed: {processed_count}, Skipped: {skipped_count}, Total: {len(scan_ids)}")
    print(f"{'='*60}\n")


def _sweep_reports(library, all_books, args):
    """Sweep through library regenerating reports from checkpoint data."""
    from pipeline.ocr import OCRStage
    from pipeline.ocr_v2 import OCRStageV2
    from pipeline.correction import CorrectionStage
    from pipeline.label import LabelStage
    from pipeline.merged import MergeStage
    from pipeline.build_structure import BuildStructureStage

    print(f"📚 Sweeping reports across {len(all_books)} books")

    # Map stage names to instances
    stage_map = {
        'ocr': OCRStage(),
        'ocr_v2': OCRStageV2(),
        'corrected': CorrectionStage(),
        'labels': LabelStage(),
        'merged': MergeStage(),
        'build_structure': BuildStructureStage(),
    }

    # Determine which stages to process
    if hasattr(args, 'stage_filter') and args.stage_filter:
        stages_to_process = [args.stage_filter]
    else:
        # All stages that support reports
        stages_to_process = ['ocr', 'corrected', 'labels']

    total_regenerated = 0

    for book in all_books:
        scan_id = book['scan_id']
        storage = library.get_book_storage(scan_id)

        for stage_name in stages_to_process:
            stage = stage_map.get(stage_name)
            if not stage:
                print(f"⚠️  Unknown stage: {stage_name}")
                continue

            # Check if checkpoint has data
            stage_storage = storage.stage(stage_name)
            checkpoint = stage_storage.checkpoint

            # For OCR stage, check PSM checkpoints instead of main checkpoint
            if stage_name == 'ocr':
                # Check if any PSM checkpoint has data
                ocr_dir = stage_storage.output_dir
                has_psm_data = False
                for psm in [3, 4, 6]:
                    psm_checkpoint_file = ocr_dir / f'psm{psm}' / '.checkpoint'
                    if psm_checkpoint_file.exists():
                        has_psm_data = True
                        break
                if not has_psm_data:
                    continue
            else:
                # Other stages: check main checkpoint
                all_metrics = checkpoint.get_all_metrics()
                if not all_metrics:
                    continue

            # Regenerate report (and run after() hook for OCR to generate selection file)
            try:
                from infra.pipeline.logger import PipelineLogger
                logger = PipelineLogger(scan_id=scan_id, stage=stage_name)

                # For OCR stage, run full after() hook to generate PSM selection + reports
                if stage_name == 'ocr':
                    metadata = storage.load_metadata()
                    total_pages = metadata.get('total_pages', 0)
                    stats = {'pages_processed': total_pages}  # Dummy stats for after()
                    stage.after(storage, checkpoint, logger, stats)
                    total_regenerated += 1
                    print(f"✅ {scan_id}/{stage_name}/ (report.csv + psm_selection.json + psm reports)")
                else:
                    # Other stages: just regenerate CSV report
                    report_path = stage.generate_report(storage, logger)
                    if report_path:
                        total_regenerated += 1
                        print(f"✅ {scan_id}/{stage_name}/report.csv ({len(all_metrics)} pages)")
            except Exception as e:
                print(f"❌ Failed to regenerate {scan_id}/{stage_name}: {e}")

    print(f"\n✅ Regenerated {total_regenerated} reports across {len(all_books)} books\n")


def cmd_sweep(args):
    """Sweep through library: run stages or regenerate reports across all books."""
    from infra.storage.library import Library

    library = Library(storage_root=Config.book_storage_root)
    all_books = library.list_books()

    if not all_books:
        print("❌ No books found in library")
        sys.exit(1)

    # Handle 'reports' sweep differently (no LLM calls, just checkpoint reads)
    if args.target == 'reports':
        _sweep_reports(library, all_books, args)
        return

    # Otherwise, sweep a pipeline stage
    _sweep_stage(library, all_books, args)


# ===== Main =====

def main():
    parser = argparse.ArgumentParser(
        prog='shelf',
        description='Scanshelf - Turn physical books into digital libraries',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Library management
  shelf shelve ~/Documents/Scans/book.pdf
  shelf shelve ~/Documents/Scans/*.pdf --run-ocr
  shelf list
  shelf stats
  shelf delete old-book --yes

  # Single book operations
  shelf show modest-lovelace
  shelf status modest-lovelace
  shelf report modest-lovelace --stage corrected
  shelf report modest-lovelace --stage labels --filter "printed_page_number="
  shelf analyze modest-lovelace --stage labels
  shelf process modest-lovelace
  shelf process modest-lovelace --stage ocr
  shelf clean modest-lovelace --stage ocr

  # Library-wide sweeps
  shelf sweep labels                    # Run labels stage across all books
  shelf sweep labels --reshuffle        # Create new random order
  shelf sweep corrected --force         # Regenerate even if completed
  shelf sweep reports                   # Regenerate all reports from checkpoints
  shelf sweep reports --stage-filter labels  # Only regenerate labels reports
"""
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    subparsers.required = True

    # ===== Library Commands =====

    # shelf shelve
    shelve_parser = subparsers.add_parser('shelve', help='Shelve book(s) into library')
    shelve_parser.add_argument('pdf_patterns', nargs='+', help='PDF file pattern(s)')
    shelve_parser.add_argument('--run-ocr', action='store_true', help='Run OCR after shelving')
    shelve_parser.set_defaults(func=cmd_shelve)

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

    # shelf stage-status
    stage_status_parser = subparsers.add_parser('stage-status', help='Show detailed stage status (for debugging)')
    stage_status_parser.add_argument('scan_id', help='Book scan ID')
    stage_status_parser.add_argument('--stage', required=True, help='Stage name')
    stage_status_parser.set_defaults(func=cmd_stage_status)

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
    process_parser.add_argument('--auto-analyze', action='store_true', dest='auto_analyze', help='Enable automatic stage analysis (disabled by default)')
    process_parser.set_defaults(func=cmd_process, auto_analyze=False)

    # ===== Clean Command =====

    # shelf clean
    clean_parser = subparsers.add_parser('clean', help='Clean stage outputs')
    clean_parser.add_argument('scan_id', help='Book scan ID')
    clean_parser.add_argument('--stage', required=True, choices=['ocr', 'corrected', 'labels', 'merged'], help='Stage to clean')
    clean_parser.add_argument('-y', '--yes', action='store_true', help='Skip confirmation')
    clean_parser.set_defaults(func=cmd_clean)

    # ===== Sweep Command =====

    # shelf sweep
    sweep_parser = subparsers.add_parser('sweep', help='Sweep through library: run stages or regenerate reports')
    sweep_parser.add_argument('target', choices=['ocr', 'corrected', 'labels', 'merged', 'build_structure', 'reports'], help='What to sweep: stage name or "reports"')
    sweep_parser.add_argument('--model', help='Vision model (for correction/label stages)')
    sweep_parser.add_argument('--workers', type=int, default=None, help='Parallel workers')
    sweep_parser.add_argument('--reshuffle', action='store_true', help='Create new random order (stages only)')
    sweep_parser.add_argument('--force', action='store_true', help='Regenerate even if completed (stages only)')
    sweep_parser.add_argument('--stage-filter', choices=['ocr', 'corrected', 'labels'], help='Filter which stage reports to regenerate (reports only)')
    sweep_parser.set_defaults(func=cmd_sweep)

    # Parse and execute
    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
