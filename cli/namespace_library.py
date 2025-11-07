import sys
import os
import glob
import json
from pathlib import Path

from infra.storage.library import Library
from infra.config import Config
from cli.helpers import get_stage_status
from cli.constants import STAGE_NAMES


def _format_time(seconds: float) -> str:
    """Format seconds as human-readable time string."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds / 60:.1f}m"
    else:
        hours = seconds / 3600
        return f"{hours:.1f}h"


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
            stage_metrics = {}
            total_cost = 0.0
            total_time = 0.0

            for stage_name in STAGE_NAMES:
                status = get_stage_status(storage, stage_name)
                if status:
                    stage_status[stage_name] = status.get('status', 'unknown')
                    metrics = status.get('metrics', {})
                    stage_cost = metrics.get('total_cost_usd', 0.0)
                    stage_runtime = metrics.get('stage_runtime_seconds', 0.0)

                    stage_metrics[stage_name] = {
                        'cost_usd': round(stage_cost, 2),
                        'runtime_seconds': round(stage_runtime, 2),
                        'runtime_minutes': round(stage_runtime / 60, 2)
                    }

                    total_cost += stage_cost
                    total_time += stage_runtime
                else:
                    stage_status[stage_name] = 'unknown'
                    stage_metrics[stage_name] = {
                        'cost_usd': 0.0,
                        'runtime_seconds': 0.0,
                        'runtime_minutes': 0.0
                    }

            books_data.append({
                'scan_id': scan_id,
                'title': scan.get('title', 'Unknown'),
                'author': scan.get('author', 'Unknown'),
                'year': scan.get('year', 'Unknown'),
                'pages': scan.get('pages', 0),
                'stage_status': stage_status,
                'stage_metrics': stage_metrics,
                'total_cost_usd': round(total_cost, 2),
                'total_runtime_seconds': round(total_time, 2),
                'total_runtime_minutes': round(total_time / 60, 2)
            })

        print(json.dumps(books_data, indent=2))
        return

    # Collect data for all books
    books_info = []
    library_cost = 0.0
    library_time = 0.0

    for scan in scans:
        scan_id = scan['scan_id']
        title = scan.get('title', 'Unknown')[:28]

        try:
            storage = library.get_book_storage(scan_id)
            stage_symbols = []
            stage_details = []
            total_cost = 0.0
            total_time = 0.0

            for stage_name in STAGE_NAMES:
                status = get_stage_status(storage, stage_name)

                if status is None:
                    stage_symbols.append('?')
                    stage_details.append({'symbol': '?', 'cost': 0.0, 'time': 0.0})
                    continue

                stage_status = status.get('status', 'not_started')
                remaining = len(status.get('remaining_pages', []))
                total = status.get('total_pages', 0)

                metrics = status.get('metrics', {})
                stage_cost = metrics.get('total_cost_usd', 0.0)
                stage_runtime = metrics.get('stage_runtime_seconds', 0.0)

                total_cost += stage_cost
                total_time += stage_runtime

                if stage_status == 'completed':
                    symbol = '✅'
                elif remaining == 0 and total > 0:
                    symbol = '✅'
                elif stage_status == 'not_started':
                    symbol = '○'
                else:
                    symbol = '⏳'

                stage_symbols.append(symbol)
                stage_details.append({
                    'symbol': symbol,
                    'cost': stage_cost,
                    'time': stage_runtime
                })

            library_cost += total_cost
            library_time += total_time

            books_info.append({
                'scan_id': scan_id,
                'title': title,
                'stage_symbols': stage_symbols,
                'stage_details': stage_details,
                'total_cost': total_cost,
                'total_time': total_time
            })
        except Exception:
            books_info.append({
                'scan_id': scan_id,
                'title': title,
                'stage_symbols': ['?'] * len(STAGE_NAMES),
                'stage_details': [{'symbol': '?', 'cost': 0.0, 'time': 0.0}] * len(STAGE_NAMES),
                'total_cost': 0.0,
                'total_time': 0.0
            })

    # Display based on mode
    if args.detailed:
        print(f"\n📚 Library ({len(scans)} books) - Detailed View\n")

        for book in books_info:
            print(f"{book['scan_id']} - {book['title']}")

            # Build stage line
            parts = []
            for i, stage_name in enumerate(STAGE_NAMES):
                detail = book['stage_details'][i]
                cost_str = f"${detail['cost']:.2f}" if detail['cost'] > 0 else "$0.00"
                time_str = _format_time(detail['time']) if detail['time'] > 0 else "0.0m"
                parts.append(f"{stage_name}: {detail['symbol']}  {cost_str:>7}  {time_str:>6}")

            print(f"  {' | '.join(parts)}")

            # Book totals
            cost_str = f"${book['total_cost']:.2f}"
            time_str = _format_time(book['total_time'])
            print(f"  Book Total: {cost_str:>7}  {time_str:>6}\n")
    else:
        print(f"\n📚 Library ({len(scans)} books)\n")
        print(f"{'Scan ID':<30} {'Title':<30} {'Cost':<10} {'Runtime':<10} {'Pipeline Status'}")
        print("-" * 120)

        for book in books_info:
            status_parts = []
            for i, stage_name in enumerate(STAGE_NAMES):
                symbol = book['stage_symbols'][i]
                status_parts.append(f"{stage_name}:{symbol}")
            status_str = " ".join(status_parts)

            cost_str = f"${book['total_cost']:.2f}" if book['total_cost'] > 0 else "-"
            time_str = _format_time(book['total_time']) if book['total_time'] > 0 else "-"

            print(f"{book['scan_id']:<30} {book['title']:<30} {cost_str:<10} {time_str:<10} {status_str}")

    # Library totals
    print("-" * 120)
    library_cost_str = f"${library_cost:.2f}"
    library_time_str = _format_time(library_time)
    library_time_hours = library_time / 3600
    print(f"{'Library Totals:':<30} {'':<30} {library_cost_str:<10} {library_time_str:<10} ({library_time_hours:.1f}h total)\n")


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
    list_parser.add_argument('--detailed', action='store_true', help='Show per-stage cost and time breakdown')
    list_parser.set_defaults(func=cmd_list)

    stats_parser = library_subparsers.add_parser('stats', help='Library statistics')
    stats_parser.set_defaults(func=cmd_stats)

    delete_parser = library_subparsers.add_parser('delete', help='Delete book from library')
    delete_parser.add_argument('scan_id', help='Book scan ID')
    delete_parser.add_argument('-y', '--yes', action='store_true', help='Skip confirmation')
    delete_parser.add_argument('--keep-files', action='store_true', help='Keep files (only remove from library)')
    delete_parser.set_defaults(func=cmd_delete)
