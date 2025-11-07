import json

from infra.pipeline.storage.library import Library
from infra.config import Config
from cli.helpers import get_stage_status
from cli.constants import STAGE_NAMES


def _format_time(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds / 60:.1f}m"
    else:
        hours = seconds / 3600
        return f"{hours:.1f}h"


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
