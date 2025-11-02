import sys
import os
import glob
from pathlib import Path

from infra.storage.library import Library
from infra.config import Config


def cmd_shelve(args):
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
    from cli.helpers import get_stage_status

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

        try:
            storage = library.get_book_storage(scan_id)
            stage_symbols = []

            for stage_name in ['ocr', 'paragraph-correct', 'label-pages', 'merged']:
                status = get_stage_status(storage, stage_name)

                if status is None:
                    stage_symbols.append('?')
                    continue

                stage_status = status.get('status', 'not_started')
                remaining = len(status.get('remaining_pages', []))
                total = status.get('total_pages', 0)

                if stage_status == 'completed':
                    stage_symbols.append('✅')
                elif remaining == 0 and total > 0:
                    stage_symbols.append('✅')
                elif stage_status == 'not_started':
                    stage_symbols.append('○')
                else:
                    stage_symbols.append('⏳')

            status_str = f"OCR:{stage_symbols[0]} COR:{stage_symbols[1]} LAB:{stage_symbols[2]} MRG:{stage_symbols[3]}"
        except Exception:
            status_str = "ERROR"

        print(f"{scan_id:<30} {title:<35} {status_str}")


def cmd_show(args):
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


def cmd_status(args):
    from cli.helpers import get_stage_status

    library = Library(storage_root=Config.book_storage_root)
    scan = library.get_scan_info(args.scan_id)

    if not scan:
        print(f"❌ Book not found: {args.scan_id}")
        sys.exit(1)

    print(f"\n📊 Pipeline Status: {args.scan_id}")
    print(f"Title: {scan['title']}")
    print("=" * 80)

    storage = library.get_book_storage(args.scan_id)

    stages = [
        ('ocr', 'OCR'),
        ('paragraph-correct', 'Paragraph-Correct'),
        ('label-pages', 'Label-Pages'),
        ('merged', 'Merge')
    ]

    for stage_name, stage_label in stages:
        status = get_stage_status(storage, stage_name)

        if status is None:
            print(f"\n? {stage_label} ({stage_name})")
            print(f"   Status: unknown")
            continue

        stage_status = status.get('status', 'not_started')
        remaining_pages = len(status.get('remaining_pages', []))
        total_pages = status.get('total_pages', 0)
        completed_pages = total_pages - remaining_pages

        if stage_status == 'completed':
            symbol = '✅'
        elif stage_status in ['not_started']:
            symbol = '○'
        elif stage_status == 'failed':
            symbol = '❌'
        else:
            symbol = '⏳'

        print(f"\n{symbol} {stage_label} ({stage_name})")
        print(f"   Status: {stage_status}")
        print(f"   Pages:  {completed_pages}/{total_pages} ({remaining_pages} remaining)")

        metrics = status.get('metrics', {})
        if metrics.get('total_cost_usd', 0) > 0:
            print(f"   Cost:   ${metrics['total_cost_usd']:.4f}")

        if metrics.get('total_time_seconds', 0) > 0:
            mins = metrics['total_time_seconds'] / 60
            print(f"   Time:   {mins:.1f}m")

        if stage_name == 'ocr':
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
                    if metrics.get('vision_cost_usd', 0) > 0:
                        print(f"      Vision cost: ${metrics['vision_cost_usd']:.4f}")

    print()


def cmd_stage_status(args):
    from cli.helpers import get_stage_status
    import json

    library = Library(storage_root=Config.book_storage_root)
    scan = library.get_scan_info(args.scan_id)

    if not scan:
        print(f"❌ Book not found: {args.scan_id}")
        sys.exit(1)

    storage = library.get_book_storage(args.scan_id)
    status = get_stage_status(storage, args.stage)

    if status is None:
        print(f"❌ Unknown stage: {args.stage}")
        print(f"Available stages: ocr, paragraph-correct, label-pages, merged")
        sys.exit(1)

    print(f"\n📊 Stage Status: {args.scan_id} / {args.stage}")
    print("=" * 80)
    print(json.dumps(status, indent=2))
    print()


def cmd_report(args):
    import csv
    from rich.console import Console
    from rich.table import Table

    library = Library(storage_root=Config.book_storage_root)
    scan = library.get_scan_info(args.scan_id)

    if not scan:
        print(f"❌ Book not found: {args.scan_id}")
        sys.exit(1)

    storage = library.get_book_storage(args.scan_id)
    stage_storage = storage.stage(args.stage)
    report_file = stage_storage.output_dir / "report.csv"

    if not report_file.exists():
        print(f"❌ No report found for stage '{args.stage}'")
        print(f"   Expected: {report_file}")
        print(f"\n   Run the stage first to generate a report.")
        sys.exit(1)

    console = Console()

    with open(report_file, 'r') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print(f"⚠️  Report is empty")
        return

    limit = None if args.all else (args.limit or 20)

    filtered_rows = rows
    if args.filter:
        filter_parts = args.filter.split('=')
        if len(filter_parts) == 2:
            col, val = filter_parts
            filtered_rows = [r for r in rows if r.get(col) == val]
        else:
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

    table = Table(title=f"{args.scan_id} - {args.stage} report ({len(filtered_rows)} rows)")

    columns = list(rows[0].keys())
    for col in columns:
        table.add_column(col, style="cyan" if col == "page_num" else None)

    display_rows = filtered_rows[:limit] if limit else filtered_rows
    for row in display_rows:
        table.add_row(*[row[col] for col in columns])

    console.print(table)

    if limit and len(filtered_rows) > limit:
        print(f"\nShowing {limit} of {len(filtered_rows)} rows. Use --all to show all rows.")


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
