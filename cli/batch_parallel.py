import os
import sys
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

from rich.console import Console
from infra.pipeline.storage.library import Library
from infra.config import Config
from cli.helpers import get_stage_status, clean_stage_directory
from cli.constants import CORE_STAGES

# Disable Rich live displays for parallel processing
os.environ['SHELF_HEADLESS'] = '1'

console = Console()
print_lock = Lock()


def safe_print(msg):
    """Thread-safe printing."""
    with print_lock:
        console.print(msg)


def process_book(scan_id: str, stage_name: str, library: Library, model: str = None, workers: int = None):
    """Process a single book's stage. Returns (scan_id, success, message)."""
    try:
        from cli.book.stage import cmd_stage_run

        storage = library.get_book_storage(scan_id)

        run_args = argparse.Namespace(
            scan_id=scan_id,
            stage_name=stage_name,
            model=model,
            workers=workers,
            delete_outputs=False
        )

        cmd_stage_run(run_args)
        return (scan_id, True, "completed")

    except KeyboardInterrupt:
        # Re-raise to let the executor handle cancellation
        raise

    except SystemExit as e:
        # cmd_stage_run calls sys.exit(1) on failure - catch it
        if e.code == 0:
            return (scan_id, True, "completed")
        return (scan_id, False, "stage failed")

    except Exception as e:
        return (scan_id, False, str(e))


def cmd_batch_parallel(args):
    library = Library(storage_root=Config.book_storage_root)
    books = library.list_books()
    scan_ids = [book['scan_id'] for book in books]

    stage_name = args.stage
    max_books = args.books or len(scan_ids)

    print(f"\n📚 {stage_name} × {len(scan_ids)} books (parallel, {max_books} at a time)\n")

    books_to_process = []
    skipped_count = 0

    if args.delete_outputs:
        print(f"⚠️  WARNING: --delete-outputs will DELETE all existing outputs")
        if not args.yes:
            try:
                response = input("   Are you sure? (yes/no): ").strip().lower()
                if response not in ['yes', 'y']:
                    print("Cancelled.")
                    sys.exit(0)
            except (EOFError, KeyboardInterrupt):
                print("\nCancelled.")
                sys.exit(0)
        print()

        for scan_id in scan_ids:
            try:
                storage = library.get_book_storage(scan_id)
                clean_stage_directory(storage, stage_name)
                console.print(f"🧹 [red]{scan_id}[/red]")
            except Exception as e:
                print(f"❌ {scan_id}: {e}")

    # Determine which books need processing
    for scan_id in scan_ids:
        try:
            storage = library.get_book_storage(scan_id)
            status = get_stage_status(storage, stage_name)

            if status and status.get('status') == 'completed':
                console.print(f"⏭️  [dim]{scan_id}[/dim]")
                skipped_count += 1
                continue

            progress = status.get('progress', {}) if status else {}
            completed = len(progress.get('completed_phases', []))
            total = progress.get('total_phases', 0)
            phase_str = f"({completed}/{total})" if total > 0 else ""

            if status and status.get('status') not in ['not_started', 'completed']:
                console.print(f"🔄 {phase_str} [yellow]{scan_id}[/yellow] - resume")
            else:
                console.print(f"▶️  {phase_str} [green]{scan_id}[/green]")

            books_to_process.append(scan_id)

        except Exception as e:
            print(f"❌ {scan_id}: {e}")
            continue

    if not books_to_process:
        print(f"\n✅ All books complete\n")
        return

    print(f"\n📖 {len(books_to_process)} books to process ({max_books} parallel)\n")

    completed_count = 0
    failed_count = 0

    with ThreadPoolExecutor(max_workers=max_books) as executor:
        futures = {
            executor.submit(
                process_book,
                scan_id,
                stage_name,
                library,
                getattr(args, 'model', None),
                getattr(args, 'workers', None)
            ): scan_id
            for scan_id in books_to_process
        }

        try:
            for future in as_completed(futures):
                scan_id, success, message = future.result()
                if success:
                    safe_print(f"✅ [green]{scan_id}[/green]: {message}")
                    completed_count += 1
                else:
                    safe_print(f"❌ [red]{scan_id}[/red]: {message}")
                    failed_count += 1
        except KeyboardInterrupt:
            print(f"\n\n⚠️  Interrupted - waiting for running books to finish...")
            executor.shutdown(wait=True, cancel_futures=True)
            sys.exit(0)

    print(f"\n🏁 {stage_name}: {completed_count} completed, {failed_count} failed, {skipped_count} skipped\n")


def setup_batch_parallel_parser(subparsers):
    parser = subparsers.add_parser(
        'batch-parallel',
        help='Run a stage across all books in parallel'
    )
    parser.add_argument('stage', choices=CORE_STAGES, help='Stage to run', metavar='STAGE')
    parser.add_argument('--books', type=int, default=4, help='Number of books to process in parallel (default: 4)')
    parser.add_argument('--model', help='Vision model override')
    parser.add_argument('--workers', type=int, default=None, help='Workers per book')
    parser.add_argument('--delete-outputs', action='store_true', help='DELETE all existing outputs before processing')
    parser.add_argument('-y', '--yes', action='store_true', help='Skip confirmation prompt')
    parser.set_defaults(func=cmd_batch_parallel)
