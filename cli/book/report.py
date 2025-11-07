import sys
import csv
import re
from rich.console import Console
from rich.table import Table

from infra.pipeline.storage.library import Library
from infra.config import Config


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
