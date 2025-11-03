import sys
import os
import glob
import json
from pathlib import Path

from infra.storage.library import Library
from infra.config import Config
from cli.helpers import get_stage_status
from cli.constants import STAGE_NAMES, STAGE_ABBRS


def cmd_add(args):
    pdf_paths = []
    for pattern in args.pdf_patterns:
        matches = glob.glob(os.path.expanduser(pattern))
        if not matches:
            print(f"⚠️  No files match pattern: {pattern}")
        pdf_paths.extend([Path(p) for p in matches])

    if not pdf_paths:
        print("❌ No PDF files found")
        sys.exit(1)

    for pdf_path in pdf_paths:
        if not pdf_path.exists():
            print(f"❌ File not found: {pdf_path}")
            sys.exit(1)
        if pdf_path.suffix.lower() != '.pdf':
            print(f"❌ Not a PDF file: {pdf_path}")
            sys.exit(1)

    try:
        library = Library(storage_root=Config.book_storage_root)
        result = library.add_books(pdf_paths=pdf_paths, run_ocr=args.run_ocr)

        print(f"\n✅ Added {result['books_added']} book(s) to library")
        for scan_id in result['scan_ids']:
            print(f"  - {scan_id}")

        if library.has_shuffle():
            print(f"   📚 Updated global shuffle order")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def cmd_list(args):
    library = Library(storage_root=Config.book_storage_root)
    scans = library.list_all_scans()

    if not scans:
        print("No books in library. Use 'shelf library add <pdf>' to add books.")
        return

    if args.json:
        books_data = []
        for scan in scans:
            scan_id = scan['scan_id']
            storage = library.get_book_storage(scan_id)

            stage_status = {}
            total_cost = 0.0
            for stage_name in STAGE_NAMES:
                status = get_stage_status(storage, stage_name)
                if status:
                    stage_status[stage_name] = status.get('status', 'unknown')
                    metrics = status.get('metrics', {})
                    total_cost += metrics.get('total_cost_usd', 0.0)
                else:
                    stage_status[stage_name] = 'unknown'

            books_data.append({
                'scan_id': scan_id,
                'title': scan.get('title', 'Unknown'),
                'author': scan.get('author', 'Unknown'),
                'year': scan.get('year', 'Unknown'),
                'pages': scan.get('pages', 0),
                'stage_status': stage_status,
                'total_cost_usd': round(total_cost, 4)
            })

        print(json.dumps(books_data, indent=2))
        return

    print(f"\n📚 Library ({len(scans)} books)\n")
    print(f"{'Scan ID':<30} {'Title':<30} {'Cost':<10} {'Pipeline Status'}")
    print("-" * 105)

    for scan in scans:
        scan_id = scan['scan_id']
        title = scan.get('title', 'Unknown')[:28]

        try:
            storage = library.get_book_storage(scan_id)
            stage_symbols = []
            total_cost = 0.0

            for stage_name in STAGE_NAMES:
                status = get_stage_status(storage, stage_name)

                if status is None:
                    stage_symbols.append('?')
                    continue

                stage_status = status.get('status', 'not_started')
                remaining = len(status.get('remaining_pages', []))
                total = status.get('total_pages', 0)

                metrics = status.get('metrics', {})
                total_cost += metrics.get('total_cost_usd', 0.0)

                if stage_status == 'completed':
                    stage_symbols.append('✅')
                elif remaining == 0 and total > 0:
                    stage_symbols.append('✅')
                elif stage_status == 'not_started':
                    stage_symbols.append('○')
                else:
                    stage_symbols.append('⏳')

            # Build status string dynamically from STAGE_ABBRS
            status_parts = []
            for i, stage_name in enumerate(STAGE_NAMES):
                abbr = STAGE_ABBRS[stage_name]
                symbol = stage_symbols[i] if i < len(stage_symbols) else '?'
                status_parts.append(f"{abbr}:{symbol}")
            status_str = " ".join(status_parts)
            cost_str = f"${total_cost:.4f}" if total_cost > 0 else "-"
        except Exception:
            status_str = "ERROR"
            cost_str = "-"

        print(f"{scan_id:<30} {title:<30} {cost_str:<10} {status_str}")


def cmd_stats(args):
    library = Library(storage_root=Config.book_storage_root)
    stats = library.get_stats()

    print(f"\n📊 Library Statistics")
    print("=" * 80)
    print(f"Total Books:  {stats['total_books']}")
    print(f"Total Scans:  {stats['total_scans']}")
    print(f"Total Pages:  {stats['total_pages']:,}")
    print(f"Total Cost:   ${stats['total_cost_usd']:.2f}")
    print()


def cmd_delete(args):
    library = Library(storage_root=Config.book_storage_root)
    scan = library.get_book_info(args.scan_id)

    if not scan:
        print(f"❌ Book not found: {args.scan_id}")
        sys.exit(1)

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

    try:
        result = library.delete_book(
            scan_id=args.scan_id,
            delete_files=not args.keep_files,
            remove_empty_book=True
        )

        print(f"\n✅ Deleted: {result['scan_id']}")
        if result['files_deleted']:
            print(f"   Files deleted from: {result['scan_dir']}")

        if library.has_shuffle():
            print(f"   📚 Removed from global shuffle order")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def setup_library_parser(subparsers):
    library_parser = subparsers.add_parser('library', help='Library management commands')
    library_subparsers = library_parser.add_subparsers(dest='library_command', help='Library command')
    library_subparsers.required = True

    add_parser = library_subparsers.add_parser('add', help='Add book(s) to library')
    add_parser.add_argument('pdf_patterns', nargs='+', help='PDF file pattern(s)')
    add_parser.add_argument('--run-ocr', action='store_true', help='Run OCR after adding')
    add_parser.set_defaults(func=cmd_add)

    list_parser = library_subparsers.add_parser('list', help='List all books')
    list_parser.add_argument('--json', action='store_true', help='Output as JSON')
    list_parser.set_defaults(func=cmd_list)

    stats_parser = library_subparsers.add_parser('stats', help='Library statistics')
    stats_parser.set_defaults(func=cmd_stats)

    delete_parser = library_subparsers.add_parser('delete', help='Delete book from library')
    delete_parser.add_argument('scan_id', help='Book scan ID')
    delete_parser.add_argument('-y', '--yes', action='store_true', help='Skip confirmation')
    delete_parser.add_argument('--keep-files', action='store_true', help='Keep files (only remove from library)')
    delete_parser.set_defaults(func=cmd_delete)
