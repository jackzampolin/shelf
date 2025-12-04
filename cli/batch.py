import sys
import argparse

from rich.console import Console
from infra.pipeline.storage.library import Library
from infra.config import Config
from cli.helpers import get_stage_status, clean_stage_directory
from cli.constants import CORE_STAGES

console = Console()


def cmd_batch(args):
    library = Library(storage_root=Config.book_storage_root)
    books = library.list_books()
    scan_ids = [book['scan_id'] for book in books]

    stages = args.stages if isinstance(args.stages, list) else [args.stages]

    if len(stages) > 1:
        print(f"\n📚 {len(stages)} stages × {len(scan_ids)} books")
        print(f"   {' → '.join(stages)}\n")
    else:
        print(f"\n📚 {stages[0]} × {len(scan_ids)} books\n")

    # Process each stage in sequence (stage-by-stage across all books)
    for stage_idx, current_stage in enumerate(stages, 1):
        if len(stages) > 1:
            print(f"\n{'─'*50}")
            print(f"Stage {stage_idx}/{len(stages)}: {current_stage}")
            print(f"{'─'*50}\n")

        books_to_process = []
        skipped_count = 0
        resumed_count = 0

        if args.delete_outputs:
            if stage_idx == 1:  # Only warn once for multi-stage
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

                if args.delete_outputs:
                    clean_stage_directory(storage, current_stage)
                    console.print(f"🧹 [red]{scan_id}[/red]")
                else:
                    status = get_stage_status(storage, current_stage)
                    progress = status.get('progress', {}) if status else {}
                    completed = len(progress.get('completed_phases', []))
                    total = progress.get('total_phases', 0)
                    current_phase = progress.get('current_phase', '')
                    phase_str = f"({completed}/{total})" if total > 0 else ""

                    if status and status.get('status') == 'completed':
                        console.print(f"⏭️  {phase_str} [dim]{scan_id}[/dim]")
                        skipped_count += 1
                        continue

                    if status and status.get('status') not in ['not_started', 'completed']:
                        console.print(f"🔄 {phase_str} [yellow]{scan_id}[/yellow] - resume {current_phase}")
                        resumed_count += 1
                    else:
                        console.print(f"▶️  {phase_str} [green]{scan_id}[/green]")

                books_to_process.append(scan_id)

            except KeyboardInterrupt:
                print(f"\n\n⚠️  Interrupted")
                sys.exit(0)
            except Exception as e:
                print(f"❌ {scan_id}: {e}")
                continue

        # Summary line
        if books_to_process:
            print(f"\n📖 {len(books_to_process)} books to process")
        else:
            print(f"\n✅ All books complete\n")
            continue  # Move to next stage

        processed_count = 0

        from cli.book.stage import cmd_stage_run

        for idx, scan_id in enumerate(books_to_process, 1):
            print(f"\n📖 {idx}. {scan_id}: processing")

            try:
                storage = library.get_book_storage(scan_id)

                run_args = argparse.Namespace(
                    scan_id=scan_id,
                    stage_name=current_stage,
                    model=getattr(args, 'model', None),
                    workers=getattr(args, 'workers', None),
                    delete_outputs=False
                )

                cmd_stage_run(run_args)
                processed_count += 1

            except KeyboardInterrupt:
                print(f"\n\n⚠️  Interrupted ({processed_count}/{len(books_to_process)} complete)")
                sys.exit(0)
            except Exception as e:
                print(f"❌ {scan_id}: {e}")
                continue

        print(f"\n🏁 {current_stage}: {processed_count} processed, {skipped_count} skipped\n")

    if len(stages) > 1:
        print(f"✅ Batch complete: {len(stages)} stages")


def setup_batch_parser(subparsers):
    batch_parser = subparsers.add_parser('batch', help='Run stage(s) across all books in library')
    batch_parser.add_argument('stages', nargs='+', choices=CORE_STAGES, help='Stage(s) to run (processes each stage across all books sequentially)', metavar='STAGE')
    batch_parser.add_argument('--model', help='Vision model (for correction/label stages)')
    batch_parser.add_argument('--workers', type=int, default=None, help='Parallel workers')
    batch_parser.add_argument('--delete-outputs', action='store_true', help='DELETE all existing outputs before processing (WARNING: irreversible)')
    batch_parser.add_argument('-y', '--yes', action='store_true', help='Skip confirmation prompt')
    batch_parser.set_defaults(func=cmd_batch)
