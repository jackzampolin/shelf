"""Stage-level command handlers."""
import sys
import json

from infra.pipeline.storage.library import Library
from infra.pipeline.runner import run_stage
from infra.config import Config
from infra.llm.display import DisplayStats, print_stage_complete
from cli.helpers import (
    clean_stage_directory,
    get_stage_status,
    get_stage_and_status,
    list_stage_phases,
)
from cli.constants import get_stage_map


def cmd_stage_run(args):
    """Run a pipeline stage."""
    library = Library(storage_root=Config.book_storage_root)
    scan = library.get_scan_info(args.scan_id)

    if not scan:
        print(f"Book not found: {args.scan_id}")
        sys.exit(1)

    storage = library.get_book_storage(args.scan_id)

    if args.delete_outputs:
        print(f"\nCleaning stage before processing: {args.stage_name}")
        clean_stage_directory(storage, args.stage_name)
        print(f"   Cleaned {args.stage_name}\n")

    stage_map = get_stage_map(
        storage,
        model=args.model,
        workers=args.workers,
        max_retries=3
    )

    if args.stage_name not in stage_map:
        print(f"Unknown stage: {args.stage_name}")
        print(f"   Valid stages: {', '.join(stage_map.keys())}")
        sys.exit(1)

    stage = stage_map[args.stage_name]

    print(f"▶️  {stage.name}")

    try:
        stats = run_stage(stage)

        # Get aggregated metrics from the stage
        aggregated = stage.stage_storage.metrics_manager.get_aggregated()

        print_stage_complete(stage.name, DisplayStats(
            completed=1,
            total=1,
            time_seconds=aggregated.get("stage_runtime_seconds", aggregated.get("total_time_seconds", 0)),
            prompt_tokens=aggregated.get("total_prompt_tokens", 0),
            completion_tokens=aggregated.get("total_completion_tokens", 0),
            reasoning_tokens=aggregated.get("total_reasoning_tokens", 0),
            cost_usd=aggregated.get("total_cost_usd", 0),
        ))
    except Exception as e:
        import traceback
        print(f"Stage failed: {e}")
        traceback.print_exc()
        sys.exit(1)


def cmd_stage_info(args):
    """Show stage status and info."""
    library = Library(storage_root=Config.book_storage_root)
    scan = library.get_scan_info(args.scan_id)

    if not scan:
        print(f"Book not found: {args.scan_id}")
        sys.exit(1)

    storage = library.get_book_storage(args.scan_id)
    stage, status = get_stage_and_status(storage, args.stage_name)

    if status is None:
        print(f"Unknown stage: {args.stage_name}")
        sys.exit(1)

    if args.json:
        print(json.dumps(status, indent=2))
        return

    stage_status = status.get('status', 'unknown')
    if stage_status == 'completed':
        symbol = '[done]'
    elif stage_status in ['not_started']:
        symbol = '[    ]'
    elif stage_status == 'failed':
        symbol = '[fail]'
    else:
        symbol = '[....]'

    print(f"\n{symbol} {args.stage_name}")
    print(stage.pretty_print_status(status))

    # Show available phases
    phases = list_stage_phases(storage, args.stage_name)
    if phases:
        print(f"\nPhases: {', '.join(phases)}")
    print()


def cmd_stage_clean(args):
    """Clean stage outputs."""
    library = Library(storage_root=Config.book_storage_root)
    scan = library.get_scan_info(args.scan_id)

    if not scan:
        print(f"Book not found: {args.scan_id}")
        sys.exit(1)

    storage = library.get_book_storage(args.scan_id)
    stage_storage = storage.stage(args.stage_name)

    if not args.yes:
        print(f"\nWARNING: This will delete all outputs for:")
        print(f"   Book:  {args.scan_id}")
        print(f"   Stage: {args.stage_name}")
        print(f"   Path:  {stage_storage.output_dir}")

        try:
            response = input("\nAre you sure? (yes/no): ").strip().lower()
            if response not in ['yes', 'y']:
                print("Cancelled.")
                return
        except EOFError:
            print("\nCancelled (no input)")
            return

    try:
        clean_stage_directory(storage, args.stage_name)
        print(f"\nCleaned stage: {args.stage_name}")
        print(f"   Deleted all outputs from: {stage_storage.output_dir}")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def cmd_stage_report(args):
    """Display stage report as table."""
    import csv
    import re
    from rich.console import Console
    from rich.table import Table

    library = Library(storage_root=Config.book_storage_root)
    scan = library.get_scan_info(args.scan_id)

    if not scan:
        print(f"Book not found: {args.scan_id}")
        sys.exit(1)

    storage = library.get_book_storage(args.scan_id)
    stage_storage = storage.stage(args.stage_name)
    report_file = stage_storage.output_dir / "report.csv"

    if not report_file.exists():
        print(f"No report found for stage '{args.stage_name}'")
        print(f"   Expected: {report_file}")
        print(f"\n   Run the stage first to generate a report.")
        sys.exit(1)

    console = Console()

    with open(report_file, 'r') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print(f"Report is empty")
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
                    print(f"Invalid filter value: {val}")
        else:
            print(f"Invalid filter format: {args.filter}")

    table = Table(title=f"{args.scan_id} - {args.stage_name} report ({len(filtered_rows)} rows)")

    columns = list(rows[0].keys())
    for col in columns:
        table.add_column(col, style="cyan" if col == "page_num" else None)

    display_rows = filtered_rows[:limit] if limit else filtered_rows
    for row in display_rows:
        table.add_row(*[row[col] for col in columns])

    console.print(table)

    if limit and len(filtered_rows) > limit:
        print(f"\nShowing {limit} of {len(filtered_rows)} rows. Use --all to show all rows.")
