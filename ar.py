#!/usr/bin/env python3
"""
AR Research CLI - Unified command-line interface for book processing

Usage:
    ar pipeline <book-slug>           # Run full pipeline
    ar scan                            # Interactive scan intake
    ar ocr <book-slug>                # OCR stage only
    ar correct <book-slug>            # Correction stage only
    ar fix <book-slug>                # Agent 4 fixes only
    ar structure <book-slug>          # Structure stage only
    ar quality <book-slug>            # Quality review stage only
    ar monitor <book-slug>            # Real-time progress monitoring
    ar review <book-slug> <action>    # Review flagged pages
    ar status <book-slug>             # Quick status check

    ar library list                   # List all books in collection
    ar library show <id>              # Show book or scan details
    ar library stats                  # Collection statistics
    ar library ingest <dir>           # Smart ingest: LLM + web search + full setup
    ar library discover <dir>         # Find new PDFs to add
    ar library migrate <folder>       # Migrate existing folder to new naming
    ar library quality <scan-id>      # Run quality assessment

Examples:
    ar pipeline The-Accidental-President
    ar quality amazing-pasteur
    ar monitor The-Accidental-President
    ar library list
    ar library ingest ~/Documents/Scans
"""

import sys
import argparse
from pathlib import Path

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))


def cmd_pipeline(args):
    """Run full pipeline or specific stages."""
    from pipeline.run import BookPipeline

    pipeline = BookPipeline(args.book_slug)
    success = pipeline.run(
        stages=args.stages,
        start_from=args.start_from,
        resume=args.resume,
        ocr_workers=args.ocr_workers,
        correct_model=args.correct_model,
        correct_workers=args.correct_workers,
        correct_rate_limit=args.correct_rate_limit,
        structure_model=args.structure_model,
        quality_model=args.quality_model
    )

    return 0 if success else 1


def cmd_scan(args):
    """Interactive scan intake."""
    from tools.scan import interactive_mode
    interactive_mode()
    return 0


def cmd_ocr(args):
    """Run OCR stage only."""
    from pipeline.ocr import BookOCRProcessor

    processor = BookOCRProcessor(max_workers=args.workers)
    processor.process_book(args.book_slug, resume=args.resume)
    return 0


def cmd_correct(args):
    """Run correction stage only."""
    from pipeline.correct import StructuredPageCorrector

    processor = StructuredPageCorrector(
        args.book_slug,
        model=args.model,
        max_workers=args.workers,
        calls_per_minute=args.rate_limit
    )
    processor.process_pages(start_page=args.start, end_page=args.end, resume=args.resume)
    return 0


def cmd_fix(args):
    """Run Agent 4 fix stage only."""
    from pipeline.fix import Agent4TargetedFix

    agent4 = Agent4TargetedFix(args.book_slug)
    agent4.process_all_flagged(resume=args.resume)
    return 0


def cmd_structure(args):
    """Run structure stage only."""
    from pipeline.structure import BookStructurer
    from pathlib import Path

    # Simple checkpoint: check if output already exists
    book_dir = Path.home() / "Documents" / "book_scans" / args.book_slug
    metadata_file = book_dir / "structured" / "metadata.json"

    if args.resume and metadata_file.exists():
        print("✅ Structure already complete")
        print(f"   Output: {book_dir / 'structured'}")
        return 0

    structurer = BookStructurer(args.book_slug, model=args.model)
    structurer.process_book()
    return 0


def cmd_quality(args):
    """Run quality review stage only."""
    from pipeline.quality_review import QualityReview

    reviewer = QualityReview(args.book_slug)
    reviewer.run()
    return 0


def cmd_status(args):
    """Check processing status (optionally with live monitoring)."""
    from tools.monitor import monitor_pipeline, print_status

    if args.watch:
        # Live monitoring
        monitor_pipeline(args.book_slug, refresh_interval=args.refresh)
    else:
        # Quick status snapshot
        print_status(args.book_slug)

    return 0


def cmd_monitor(args):
    """Real-time progress monitoring (deprecated - use 'status --watch')."""
    print("⚠️  'ar monitor' is deprecated. Please use 'ar status --watch' instead.\n")

    from tools.monitor import monitor_pipeline

    monitor_pipeline(args.book_slug, refresh_interval=args.refresh)
    return 0


def cmd_review(args):
    """Review flagged pages."""
    from tools.review import main as review_main

    # Construct arguments for review tool
    sys.argv = ['review.py', args.book_slug, args.action]
    if args.page:
        sys.argv.append(f'--page={args.page}')

    review_main()
    return 0


def cmd_library_list(args):
    """List all books in the collection."""
    from tools.library import LibraryIndex

    library = LibraryIndex()
    books = library.list_all_books()

    if not books:
        print("No books in library yet.")
        print("\nAdd books with: ar library discover <directory>")
        return 0

    print(f"\n📚 Library ({len(books)} book(s))\n")
    print(f"{'Title':<50} {'Author':<30} {'Scans':>6}")
    print("=" * 88)

    for book in books:
        title = book['title'][:48] if book['title'] and len(book['title']) > 48 else (book['title'] or 'Unknown')
        author = book['author'][:28] if book['author'] and len(book['author']) > 28 else (book['author'] or 'Unknown')
        print(f"{title:<50} {author:<30} {book['scan_count']:>6}")

    return 0


def cmd_library_show(args):
    """Show details for a book or scan."""
    from tools.library import LibraryIndex

    library = LibraryIndex()

    # Try as scan_id first
    scan_info = library.get_scan_info(args.identifier)
    if scan_info:
        print(f"\n📖 {scan_info['title']}")
        print(f"   By {scan_info['author']}")
        if scan_info.get('isbn'):
            print(f"   ISBN: {scan_info['isbn']}")
        print()

        scan = scan_info['scan']
        print(f"Scan: {scan['scan_id']}")
        print(f"  Status: {scan['status']}")
        print(f"  Added: {scan['date_added'][:10]}")
        print(f"  Pages: {scan.get('pages', 0)}")
        print(f"  Cost: ${scan.get('cost_usd', 0):.2f}")

        if scan.get('models'):
            print(f"  Models:")
            for stage, model in scan['models'].items():
                print(f"    {stage}: {model}")

        if scan.get('notes'):
            print(f"  Notes: {scan['notes']}")

        return 0

    # Try as book slug
    scans = library.get_book_scans(args.identifier)
    if scans:
        book = library.data['books'][args.identifier]
        print(f"\n📖 {book['title']}")
        print(f"   By {book['author']}")
        if book.get('isbn'):
            print(f"   ISBN: {book['isbn']}")
        print()

        print(f"Scans ({len(scans)}):")
        for scan in scans:
            print(f"  • {scan['scan_id']}")
            print(f"    Status: {scan['status']} | Pages: {scan.get('pages', 0)} | Cost: ${scan.get('cost_usd', 0):.2f}")

        return 0

    print(f"Not found: {args.identifier}")
    return 1


def cmd_library_scans(args):
    """List all scans for a book."""
    from tools.library import LibraryIndex

    library = LibraryIndex()
    scans = library.get_book_scans(args.book_slug)

    if not scans:
        print(f"No scans found for: {args.book_slug}")
        return 1

    book = library.data['books'][args.book_slug]
    print(f"\n📖 {book['title']}")
    print(f"   By {book['author']}\n")

    for scan in scans:
        print(f"  {scan['scan_id']}")
        print(f"    Status: {scan['status']}")
        print(f"    Added: {scan['date_added'][:10]}")
        print(f"    Pages: {scan.get('pages', 0)}")
        print(f"    Cost: ${scan.get('cost_usd', 0):.2f}")
        if scan.get('notes'):
            print(f"    Notes: {scan['notes']}")
        print()

    return 0


def cmd_library_stats(args):
    """Show library-wide statistics."""
    from tools.library import LibraryIndex

    library = LibraryIndex()
    stats = library.get_stats()

    print("\n📊 Library Statistics\n")
    print(f"Books:       {stats['total_books']}")
    print(f"Scans:       {stats['total_scans']}")
    print(f"Pages:       {stats['total_pages']:,}")
    print(f"Total Cost:  ${stats['total_cost_usd']:.2f}")

    if stats['total_pages'] > 0:
        avg_cost_per_page = stats['total_cost_usd'] / stats['total_pages']
        print(f"Cost/Page:   ${avg_cost_per_page:.4f}")

    return 0


def cmd_add(args):
    """Add book(s) to library with metadata extraction."""
    from tools.ingest import group_batch_pdfs, ingest_book_group
    from tools.library import LibraryIndex

    # Convert PDF paths to list
    pdf_paths = [Path(p).expanduser() for p in args.pdfs]

    # Validate PDFs exist
    for pdf_path in pdf_paths:
        if not pdf_path.exists():
            print(f"❌ Error: PDF not found: {pdf_path}")
            return 1

    # Group PDFs by base name (e.g., book-1.pdf, book-2.pdf → "book")
    groups = group_batch_pdfs(pdf_paths)

    print(f"Found {len(pdf_paths)} PDF(s) in {len(groups)} book(s)\n")

    # Process each book group
    library = LibraryIndex()
    scan_ids = []

    for base_name, pdfs in groups.items():
        print(f"📚 Processing: {base_name}")
        print(f"   PDFs: {len(pdfs)}")

        scan_id = ingest_book_group(
            base_name=base_name,
            pdf_paths=pdfs,
            library=library,
            auto_confirm=args.yes
        )

        if scan_id:
            scan_ids.append(scan_id)
            print()

    if scan_ids:
        print(f"✅ Added {len(scan_ids)} book(s) to library")
        return 0
    else:
        print("❌ No books were added")
        return 1


def cmd_library_ingest(args):
    """Smart ingest with LLM + web search (deprecated - use 'ar add' instead)."""
    print("⚠️  'ar library ingest' is deprecated. Please use 'ar add' instead.")
    print("   Example: ar add ~/Documents/Scans/*.pdf\n")

    from tools.ingest import ingest_from_directories

    directories = [Path(args.directory).expanduser()]
    scan_ids = ingest_from_directories(directories, auto_confirm=args.yes)

    return 0 if scan_ids else 1


def cmd_library_discover(args):
    """Discover new PDFs and add to library."""
    from tools.library import LibraryIndex
    from tools.discover import discover_books_in_directory
    from tools.names import ensure_unique_scan_id
    import shutil

    library = LibraryIndex()
    directory = Path(args.directory).expanduser()

    print(f"\n🔍 Scanning: {directory}\n")

    # Discover PDFs
    discovered = discover_books_in_directory(directory)

    if not discovered:
        print("No PDFs found.")
        return 0

    print(f"\nFound {len(discovered)} book(s)\n")

    # Process each discovered book
    for item in discovered:
        pdf_path = item['pdf_path']
        metadata = item['metadata']

        title = metadata.get('title', pdf_path.stem)
        author = metadata.get('author', 'Unknown')

        print(f"\n📖 {title}")
        print(f"   By {author}")

        # Ask user to confirm
        response = input("   Add to library? (y/n): ").strip().lower()

        if response != 'y':
            print("   Skipped.")
            continue

        # Generate unique scan ID
        existing_ids = [
            scan['scan_id']
            for book in library.data['books'].values()
            for scan in book['scans']
        ]
        scan_id = ensure_unique_scan_id(existing_ids)

        # Create scan directory
        scan_dir = library.storage_root / scan_id
        scan_dir.mkdir(exist_ok=True)

        # Copy PDF to source/
        source_dir = scan_dir / "source"
        source_dir.mkdir(exist_ok=True)
        dest_pdf = source_dir / pdf_path.name
        shutil.copy2(pdf_path, dest_pdf)

        # Add to library
        library.add_book(
            title=title,
            author=author,
            scan_id=scan_id,
            isbn=metadata.get('isbn'),
            year=metadata.get('year'),
            publisher=metadata.get('publisher'),
            source_file=pdf_path.name
        )

        print(f"   ✓ Added as: {scan_id}")

    return 0


def cmd_library_migrate(args):
    """Migrate existing folder to new naming system."""
    from tools.library import LibraryIndex

    library = LibraryIndex()

    print(f"\n🔄 Migrating: {args.folder_name}\n")

    try:
        scan_id = library.migrate_existing_folder(
            args.folder_name,
            title=args.title,
            author=args.author
        )

        print(f"✓ Migrated to: {scan_id}")

        # Show new path
        new_path = library.storage_root / scan_id
        print(f"  New path: {new_path}")

        return 0

    except Exception as e:
        print(f"✗ Migration failed: {e}")
        return 1


def cmd_library_quality(args):
    """Run quality assessment on a scan."""
    from tools.quality_check import QualityAssessment

    qa = QualityAssessment(args.scan_id)
    qa.run_full_assessment()
    qa.print_report()
    return 0


def cmd_library_validate(args):
    """Validate library consistency with disk state."""
    from tools.library import LibraryIndex

    library = LibraryIndex()

    print("\nValidating library consistency...\n")
    validation = library.validate_library()

    # Print stats
    stats = validation["stats"]
    print(f"Scans in library:    {stats['total_scans_in_library']}")
    print(f"Scan dirs on disk:   {stats['total_scan_dirs_on_disk']}")
    print()

    if validation["valid"]:
        print("Library is consistent with disk state.")
        return 0

    # Print issues
    print(f"Found {len(validation['issues'])} issue(s):\n")

    issue_types = {
        "missing_scan_dir": "Missing Scan Directory",
        "orphaned_scan_dir": "Orphaned Scan Directory",
        "cost_mismatch": "Cost Mismatch",
        "model_mismatch": "Model Mismatch",
        "validation_error": "Validation Error"
    }

    for issue in validation["issues"]:
        issue_label = issue_types.get(issue["type"], issue["type"])
        print(f"[{issue_label}] {issue['scan_id']}")
        print(f"  {issue['details']}")
        if issue.get("expected") is not None:
            print(f"  Expected: {issue['expected']}")
        if issue.get("actual") is not None:
            print(f"  Actual:   {issue['actual']}")
        print()

    # Print summary by type
    print("Summary:")
    if stats["missing_scan_dirs"] > 0:
        print(f"  Missing scan directories:  {stats['missing_scan_dirs']}")
    if stats["orphaned_scan_dirs"] > 0:
        print(f"  Orphaned scan directories: {stats['orphaned_scan_dirs']}")
    if stats["cost_mismatches"] > 0:
        print(f"  Cost mismatches:           {stats['cost_mismatches']}")
    if stats["model_mismatches"] > 0:
        print(f"  Model mismatches:          {stats['model_mismatches']}")

    # Auto-fix if requested
    if args.fix:
        print("\nAttempting auto-fix...\n")
        fix_result = library.auto_fix_validation_issues(validation)

        if fix_result["fixed_count"] > 0:
            print(f"Fixed {fix_result['fixed_count']} issue(s):")
            for issue_type in set(fix_result["fixed_issues"]):
                count = fix_result["fixed_issues"].count(issue_type)
                print(f"  - {issue_types.get(issue_type, issue_type)}: {count}")
            print()

        if fix_result["unfixable_count"] > 0:
            print(f"Could not fix {fix_result['unfixable_count']} issue(s):")
            for issue_type in set(fix_result["unfixable_issues"]):
                count = fix_result["unfixable_issues"].count(issue_type)
                print(f"  - {issue_types.get(issue_type, issue_type)}: {count}")
            print("\nThese issues require manual intervention.")

        # Re-validate
        print("\nRe-validating...\n")
        validation = library.validate_library()
        if validation["valid"]:
            print("Library is now consistent!")
            return 0
        else:
            print(f"Still have {len(validation['issues'])} issue(s) remaining.")
            return 1

    return 1


def cmd_library_delete(args):
    """Delete a book from the library (removes directory and metadata)."""
    from tools.library import LibraryIndex
    import shutil

    library = LibraryIndex()
    scan_id = args.scan_id

    # Check if scan exists
    scan_dir = library.storage_root / scan_id

    if not scan_dir.exists():
        print(f"❌ Error: Scan directory not found: {scan_dir}")
        return 1

    # Check if in library
    scan_in_library = any(
        scan_id in [s['scan_id'] for s in book['scans']]
        for book in library.data['books'].values()
    )

    if not scan_in_library:
        print(f"⚠️  Warning: '{scan_id}' not found in library.json")
        print(f"   But directory exists: {scan_dir}")
        response = input("   Delete directory anyway? (y/n): ").strip().lower()
        if response != 'y':
            return 1

    # Confirm deletion
    if not args.yes:
        print(f"\n🗑️  Delete: {scan_id}")
        print(f"   Directory: {scan_dir}")
        if scan_in_library:
            print(f"   Will also remove from library.json")
        response = input("\n   Are you sure? (y/n): ").strip().lower()
        if response != 'y':
            print("   Cancelled.")
            return 0

    # Delete directory
    if scan_dir.exists():
        print(f"   Deleting directory...")
        shutil.rmtree(scan_dir)
        print(f"   ✓ Deleted: {scan_dir}")

    # Remove from library.json
    if scan_in_library:
        with library._lock:
            # Find and remove scan
            for book_id, book in library.data['books'].items():
                book['scans'] = [s for s in book['scans'] if s['scan_id'] != scan_id]

                # Remove book if no scans left
                if not book['scans']:
                    del library.data['books'][book_id]
                    print(f"   ✓ Removed book from library (no scans remaining)")
                    break

            library.save()
            print(f"   ✓ Updated library.json")

    print(f"\n✅ Deleted: {scan_id}")
    return 0


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description='AR Research - Book Processing Pipeline',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # =========================================================================
    # PROCESS command
    # =========================================================================
    process_parser = subparsers.add_parser('process', help='Process book through all stages (OCR → Correct → Fix → Structure)')
    process_parser.add_argument('book_slug', help='Book scan-id (e.g., accidental-president)')
    process_parser.add_argument('--stages', nargs='+',
                                choices=['ocr', 'correct', 'fix', 'structure', 'quality'],
                                help='Run only specific stages')
    process_parser.add_argument('--start-from', choices=['ocr', 'correct', 'fix', 'structure', 'quality'],
                                help='Start from this stage')
    process_parser.add_argument('--resume', action='store_true',
                                help='Resume from checkpoints (skip completed pages in all stages)')
    process_parser.add_argument('--ocr-workers', type=int, default=8,
                                help='OCR parallel workers (default: 8)')
    process_parser.add_argument('--correct-model', default='openai/gpt-4o-mini',
                                help='Correction model (default: openai/gpt-4o-mini)')
    process_parser.add_argument('--correct-workers', type=int, default=30,
                                help='Correction parallel workers (default: 30)')
    process_parser.add_argument('--correct-rate-limit', type=int, default=150,
                                help='Correction API calls/min (default: 150)')
    process_parser.add_argument('--structure-model', default='anthropic/claude-sonnet-4.5',
                                help='Structure model (default: anthropic/claude-sonnet-4.5)')
    process_parser.add_argument('--quality-model', default='anthropic/claude-sonnet-4.5',
                                help='Quality review model (default: anthropic/claude-sonnet-4.5)')
    process_parser.set_defaults(func=cmd_pipeline)

    # =========================================================================
    # ADD command
    # =========================================================================
    add_parser = subparsers.add_parser('add', help='Add book(s) to library with metadata extraction')
    add_parser.add_argument('pdfs', nargs='+', help='PDF file(s) to add (supports wildcards)')
    add_parser.add_argument('-y', '--yes', action='store_true', help='Skip confirmation prompts')
    add_parser.add_argument('--id', dest='custom_id', help='Custom scan-id (default: auto-generate from title)')
    add_parser.set_defaults(func=cmd_add)

    # =========================================================================
    # SCAN command
    # =========================================================================
    scan_parser = subparsers.add_parser('scan', help='Interactive scan intake')
    scan_parser.set_defaults(func=cmd_scan)

    # =========================================================================
    # OCR command
    # =========================================================================
    ocr_parser = subparsers.add_parser('ocr', help='Run OCR stage only')
    ocr_parser.add_argument('book_slug', help='Book slug')
    ocr_parser.add_argument('--workers', type=int, default=8,
                           help='Parallel workers (default: 8)')
    ocr_parser.add_argument('--resume', action='store_true',
                           help='Resume from checkpoint (skip completed pages)')
    ocr_parser.set_defaults(func=cmd_ocr)

    # =========================================================================
    # CORRECT command
    # =========================================================================
    correct_parser = subparsers.add_parser('correct', help='Run correction stage only')
    correct_parser.add_argument('book_slug', help='Book slug')
    correct_parser.add_argument('--model', default='openai/gpt-4o-mini',
                               help='Model (default: openai/gpt-4o-mini)')
    correct_parser.add_argument('--workers', type=int, default=30,
                               help='Parallel workers (default: 30)')
    correct_parser.add_argument('--rate-limit', type=int, default=150,
                               help='API calls/min (default: 150)')
    correct_parser.add_argument('--start', type=int, default=1,
                               help='Start page (default: 1)')
    correct_parser.add_argument('--end', type=int, default=None,
                               help='End page (default: all)')
    correct_parser.add_argument('--resume', action='store_true',
                               help='Resume from checkpoint (skip completed pages)')
    correct_parser.set_defaults(func=cmd_correct)

    # =========================================================================
    # FIX command
    # =========================================================================
    fix_parser = subparsers.add_parser('fix', help='Run Agent 4 fixes only')
    fix_parser.add_argument('book_slug', help='Book slug')
    fix_parser.add_argument('--resume', action='store_true',
                           help='Resume from checkpoint (skip completed pages)')
    fix_parser.set_defaults(func=cmd_fix)

    # =========================================================================
    # STRUCTURE command
    # =========================================================================
    structure_parser = subparsers.add_parser('structure', help='Run structure stage only')
    structure_parser.add_argument('book_slug', help='Book slug')
    structure_parser.add_argument('--model', default='anthropic/claude-sonnet-4.5',
                                 help='Model (default: anthropic/claude-sonnet-4.5)')
    structure_parser.add_argument('--resume', action='store_true',
                                 help='Skip if structure already complete')
    structure_parser.set_defaults(func=cmd_structure)

    # =========================================================================
    # QUALITY command
    # =========================================================================
    quality_parser = subparsers.add_parser('quality', help='Run quality review stage only')
    quality_parser.add_argument('book_slug', help='Book slug')
    quality_parser.add_argument('--model', default='anthropic/claude-sonnet-4.5',
                                help='Model (default: anthropic/claude-sonnet-4.5)')
    quality_parser.set_defaults(func=cmd_quality)

    # =========================================================================
    # STATUS command
    # =========================================================================
    status_parser = subparsers.add_parser('status', help='Check processing status')
    status_parser.add_argument('book_slug', help='Book scan-id')
    status_parser.add_argument('--watch', action='store_true',
                              help='Live monitoring with real-time updates')
    status_parser.add_argument('--refresh', type=int, default=5,
                              help='Refresh interval in seconds when using --watch (default: 5)')
    status_parser.set_defaults(func=cmd_status)

    # =========================================================================
    # MONITOR command (deprecated - use 'status --watch')
    # =========================================================================
    monitor_parser = subparsers.add_parser('monitor', help='[DEPRECATED] Use "status --watch" instead')
    monitor_parser.add_argument('book_slug', help='Book scan-id')
    monitor_parser.add_argument('--refresh', type=int, default=5,
                               help='Refresh interval in seconds (default: 5)')
    monitor_parser.set_defaults(func=cmd_monitor)

    # =========================================================================
    # REVIEW command
    # =========================================================================
    review_parser = subparsers.add_parser('review', help='Review flagged pages')
    review_parser.add_argument('book_slug', help='Book scan-id')
    review_parser.add_argument('action', choices=['report', 'checklist', 'accept'],
                              help='Action to perform')
    review_parser.add_argument('--page', type=int, help='Specific page to review')
    review_parser.set_defaults(func=cmd_review)

    # =========================================================================
    # LIBRARY command group
    # =========================================================================
    library_parser = subparsers.add_parser('library', help='Library management commands')
    library_subparsers = library_parser.add_subparsers(dest='library_command', help='Library commands')

    # library list
    list_parser = library_subparsers.add_parser('list', help='List all books in collection')
    list_parser.set_defaults(func=cmd_library_list)

    # library show
    show_parser = library_subparsers.add_parser('show', help='Show book or scan details')
    show_parser.add_argument('identifier', help='Book slug or scan ID')
    show_parser.set_defaults(func=cmd_library_show)

    # library scans
    scans_parser = library_subparsers.add_parser('scans', help='List all scans for a book')
    scans_parser.add_argument('book_slug', help='Book slug')
    scans_parser.set_defaults(func=cmd_library_scans)

    # library stats
    stats_parser = library_subparsers.add_parser('stats', help='Show library statistics')
    stats_parser.set_defaults(func=cmd_library_stats)

    # library ingest
    ingest_parser = library_subparsers.add_parser('ingest', help='Smart ingest with LLM + web search')
    ingest_parser.add_argument('directory', help='Directory to scan for PDFs')
    ingest_parser.add_argument('-y', '--yes', action='store_true', help='Skip confirmation prompts')
    ingest_parser.set_defaults(func=cmd_library_ingest)

    # library discover
    discover_parser = library_subparsers.add_parser('discover', help='Discover new PDFs in directory')
    discover_parser.add_argument('directory', help='Directory to scan for PDFs')
    discover_parser.set_defaults(func=cmd_library_discover)

    # library migrate
    migrate_parser = library_subparsers.add_parser('migrate', help='Migrate existing folder to new naming')
    migrate_parser.add_argument('folder_name', help='Current folder name')
    migrate_parser.add_argument('--title', help='Book title (optional, will read from metadata)')
    migrate_parser.add_argument('--author', help='Book author (optional, will read from metadata)')
    migrate_parser.set_defaults(func=cmd_library_migrate)

    # library quality
    quality_parser = library_subparsers.add_parser('quality', help='Run quality assessment on a scan')
    quality_parser.add_argument('scan_id', help='Scan ID to assess')
    quality_parser.set_defaults(func=cmd_library_quality)

    # library validate
    validate_parser = library_subparsers.add_parser('validate', help='Validate library consistency with disk')
    validate_parser.add_argument('--fix', action='store_true', help='Automatically fix issues where possible')
    validate_parser.set_defaults(func=cmd_library_validate)

    # library delete
    delete_parser = library_subparsers.add_parser('delete', help='Delete a book from the library')
    delete_parser.add_argument('scan_id', help='Scan ID to delete')
    delete_parser.add_argument('-y', '--yes', action='store_true', help='Skip confirmation prompt')
    delete_parser.set_defaults(func=cmd_library_delete)

    # Parse and execute
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    try:
        return args.func(args)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
