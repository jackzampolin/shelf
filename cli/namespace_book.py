import sys
import csv
import re
import json
from rich.console import Console
from rich.table import Table

from infra.storage.library import Library
from infra.pipeline.runner import run_stage, run_pipeline
from infra.config import Config
from cli.helpers import get_stage_status, get_stage_and_status, clean_stage_directory
from cli.constants import CORE_STAGES, REPORT_STAGES


def cmd_info(args):
    library = Library(storage_root=Config.book_storage_root)
    scan = library.get_scan_info(args.scan_id)

    if not scan:
        print(f"❌ Book not found: {args.scan_id}")
        sys.exit(1)

    storage = library.get_book_storage(args.scan_id)

    stage_labels = {
        'ocr': 'OCR',
        'chandra-ocr': 'Chandra-OCR',
        'paragraph-correct': 'Paragraph-Correct',
        'label-pages': 'Label-Pages',
        'extract-toc': 'Extract-ToC',
    }

    if args.json:
        if args.stage:
            status = get_stage_status(storage, args.stage)
            if status is None:
                print(f"❌ Unknown stage: {args.stage}")
                sys.exit(1)
            print(json.dumps(status, indent=2))
        else:
            all_status = {'metadata': scan, 'stages': {}}
            for stage_name in CORE_STAGES:
                status = get_stage_status(storage, stage_name)
                if status:
                    all_status['stages'][stage_name] = status
            print(json.dumps(all_status, indent=2))
        return

    if args.stage:
        stage, status = get_stage_and_status(storage, args.stage)
        if status is None:
            print(f"❌ Unknown stage: {args.stage}")
            print(f"Available stages: {', '.join(CORE_STAGES)}")
            sys.exit(1)

        stage_labels = {
            'ocr': 'OCR',
            'chandra-ocr': 'Chandra-OCR',
            'paragraph-correct': 'Paragraph-Correct',
            'label-pages': 'Label-Pages',
            'extract-toc': 'Extract-ToC',
        }
        stage_label = stage_labels.get(args.stage, args.stage.title())

        stage_status = status.get('status', 'unknown')
        if stage_status == 'completed':
            symbol = '✅'
        elif stage_status in ['not_started']:
            symbol = '○'
        elif stage_status == 'failed':
            symbol = '❌'
        else:
            symbol = '⏳'

        print(f"\n{symbol} {stage_label} ({args.stage})")
        print(stage.pretty_print_status(status))
        print()
        return

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

    print(f"\n📊 Pipeline Status")
    print("=" * 80)

    stage_labels = {
        'ocr': 'OCR',
        'chandra-ocr': 'Chandra-OCR',
        'paragraph-correct': 'Paragraph-Correct',
        'label-pages': 'Label-Pages',
        'extract-toc': 'Extract-ToC'
    }

    total_cost = 0.0

    for stage_name in CORE_STAGES:
        stage_label = stage_labels[stage_name]
        stage, status = get_stage_and_status(storage, stage_name)

        if status is None:
            print(f"\n? {stage_label} ({stage_name})")
            print(f"   Status: unknown")
            continue

        stage_status = status.get('status', 'not_started')

        if stage_status == 'completed':
            symbol = '✅'
        elif stage_status in ['not_started']:
            symbol = '○'
        elif stage_status == 'failed':
            symbol = '❌'
        else:
            symbol = '⏳'

        print(f"\n{symbol} {stage_label} ({stage_name})")
        print(stage.pretty_print_status(status))

        metrics = status.get('metrics', {})
        stage_cost = metrics.get('total_cost_usd', 0)
        total_cost += stage_cost

    if total_cost > 0:
        print(f"\n💰 Total Pipeline Cost: ${total_cost:.4f}")
    print()


def cmd_report(args):
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
        match = re.match(r'([^>=<!]+)(>=|<=|>|<|=)(.+)', args.filter)
        if match:
            col, op, val = match.groups()
            col = col.strip()
            val = val.strip()

            if op == '=':
                filtered_rows = [r for r in rows if r.get(col) == val]
            else:
                try:
                    val_num = float(val)
                    if op == '>':
                        filtered_rows = [r for r in rows if float(r.get(col, 0)) > val_num]
                    elif op == '<':
                        filtered_rows = [r for r in rows if float(r.get(col, 0)) < val_num]
                    elif op == '>=':
                        filtered_rows = [r for r in rows if float(r.get(col, 0)) >= val_num]
                    elif op == '<=':
                        filtered_rows = [r for r in rows if float(r.get(col, 0)) <= val_num]
                except (ValueError, TypeError):
                    print(f"⚠️  Invalid filter value: {val}")
        else:
            print(f"⚠️  Invalid filter format: {args.filter}")

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


def cmd_run_stage(args):
    from cli.constants import get_stage_map

    library = Library(storage_root=Config.book_storage_root)
    scan = library.get_scan_info(args.scan_id)

    if not scan:
        print(f"❌ Book not found: {args.scan_id}")
        sys.exit(1)

    storage = library.get_book_storage(args.scan_id)

    stage_map = get_stage_map(
        model=args.model,
        workers=args.workers,
        max_retries=3
    )

    if args.stage not in stage_map:
        print(f"❌ Unknown stage: {args.stage}")
        print(f"   Valid stages: {', '.join(stage_map.keys())}")
        sys.exit(1)

    stage = stage_map[args.stage]

    if args.clean:
        print(f"\n🧹 Cleaning stage before processing: {args.stage}")
        clean_stage_directory(storage, args.stage)
        print(f"   ✓ Cleaned {args.stage}\n")

    try:
        print(f"\n🔧 Running stage: {stage.name}")
        stats = run_stage(stage, storage)
        print(f"\n✅ Stage complete: {stage.name}")
    except Exception as e:
        print(f"\n❌ Stage failed: {e}")
        sys.exit(1)


def cmd_process(args):
    from pipeline.ocr import OCRStage
    from pipeline.paragraph_correct import ParagraphCorrectStage
    from pipeline.label_pages import LabelPagesStage
    from pipeline.extract_toc import ExtractTocStage

    library = Library(storage_root=Config.book_storage_root)
    scan = library.get_scan_info(args.scan_id)

    if not scan:
        print(f"❌ Book not found: {args.scan_id}")
        sys.exit(1)

    storage = library.get_book_storage(args.scan_id)

    stages = [
        OCRStage(max_workers=args.workers if args.workers else None),
        ParagraphCorrectStage(
            model=args.model,
            max_workers=args.workers if args.workers else 30,
            max_retries=3
        ),
        LabelPagesStage(
            model=args.model,
            max_workers=args.workers if args.workers else 30,
            max_retries=3
        ),
        ExtractTocStage(model=args.model)
    ]

    if args.clean:
        print(f"\n🧹 Cleaning all stages before processing")
        for stage_name in CORE_STAGES:
            clean_stage_directory(storage, stage_name)
            print(f"   ✓ Cleaned {stage_name}")
        print()

    try:
        print(f"\n🔧 Running pipeline: {', '.join(s.name for s in stages)}")
        results = run_pipeline(stages, storage, stop_on_error=True)
        print(f"\n✅ Pipeline complete: {len(results)} stages")
    except Exception as e:
        print(f"\n❌ Pipeline failed: {e}")
        sys.exit(1)


def cmd_clean(args):
    library = Library(storage_root=Config.book_storage_root)
    scan = library.get_scan_info(args.scan_id)

    if not scan:
        print(f"❌ Book not found: {args.scan_id}")
        sys.exit(1)

    storage = library.get_book_storage(args.scan_id)
    stage_storage = storage.stage(args.stage)

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

    try:
        clean_stage_directory(storage, args.stage)
        print(f"\n✅ Cleaned stage: {args.stage}")
        print(f"   Deleted all outputs from: {stage_storage.output_dir}")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


def setup_book_parser(subparsers):
    book_parser = subparsers.add_parser('book', help='Single book operations')
    book_parser.add_argument('scan_id', help='Book scan ID')

    book_subparsers = book_parser.add_subparsers(dest='book_command', help='Book command')
    book_subparsers.required = True

    info_parser = book_subparsers.add_parser('info', help='Show book metadata and pipeline status')
    info_parser.add_argument('--stage', choices=CORE_STAGES, help='Show detailed status for one stage')
    info_parser.add_argument('--json', action='store_true', help='Output as JSON')
    info_parser.set_defaults(func=cmd_info)

    report_parser = book_subparsers.add_parser('report', help='Display stage report as table')
    report_parser.add_argument('--stage', required=True, choices=REPORT_STAGES, help='Stage to show report for')
    report_parser.add_argument('--limit', type=int, help='Number of rows to show (default: 20)')
    report_parser.add_argument('--all', '-a', action='store_true', help='Show all rows')
    report_parser.add_argument('--filter', help='Filter rows (e.g., "page_num=5" or "total_corrections>10"). Operators: = > < >= <=')
    report_parser.set_defaults(func=cmd_report)

    run_stage_parser = book_subparsers.add_parser('run-stage', help='Run a single pipeline stage')
    run_stage_parser.add_argument('stage', choices=CORE_STAGES, help='Stage to run')
    run_stage_parser.add_argument('--model', help='Vision model (for correction/label stages)')
    run_stage_parser.add_argument('--workers', type=int, default=None, help='Parallel workers')
    run_stage_parser.add_argument('--clean', action='store_true', help='DELETE stage outputs before processing (WARNING: irreversible)')
    run_stage_parser.set_defaults(func=cmd_run_stage)

    process_parser = book_subparsers.add_parser('process', help='Run all pipeline stages')
    process_parser.add_argument('--model', help='Vision model (for correction/label stages)')
    process_parser.add_argument('--workers', type=int, default=None, help='Parallel workers')
    process_parser.add_argument('--clean', action='store_true', help='DELETE all stage outputs before processing (WARNING: irreversible)')
    process_parser.set_defaults(func=cmd_process)

    clean_parser = book_subparsers.add_parser('clean', help='Clean stage outputs')
    clean_parser.add_argument('--stage', required=True, choices=CORE_STAGES, help='Stage to clean')
    clean_parser.add_argument('-y', '--yes', action='store_true', help='Skip confirmation')
    clean_parser.set_defaults(func=cmd_clean)
