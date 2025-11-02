import sys
import argparse

from infra.storage.library import Library
from infra.config import Config
from cli.helpers import get_stage_status, clean_stage_directory
from cli.constants import CORE_STAGES


def cmd_batch(args):
    library = Library(storage_root=Config.book_storage_root)
    scan_ids = library.create_shuffle(reshuffle=args.reshuffle)
    shuffle_info = library.get_shuffle_info()

    if args.reshuffle:
        print(f"🔀 Created new global shuffle order")
    elif shuffle_info:
        created_date = shuffle_info.get('created_at', '')[:10] if 'created_at' in shuffle_info else 'unknown'
        print(f"♻️  Using existing global shuffle order (created: {created_date})")
    else:
        print(f"🎲 Created random order")

    print(f"\n🧹 Sweeping '{args.stage}' stage across {len(scan_ids)} books")
    print(f"   Press Ctrl+C to stop at any time")
    print(f"   Tip: Use --reshuffle to create a new random order\n")

    books_to_process = []
    skipped_count = 0

    if args.force:
        print("Phase 1: Checking status and cleaning...")
    else:
        print("Phase 1: Checking status (resume mode)...")

    for idx, scan_id in enumerate(scan_ids, 1):
        try:
            storage = library.get_book_storage(scan_id)

            if args.force:
                print(f"  [{idx}/{len(scan_ids)}] 🧹 {scan_id}: Cleaning {args.stage} stage...")
                clean_stage_directory(storage, args.stage)
            else:
                status = get_stage_status(storage, args.stage)
                if status and status.get('status') == 'completed':
                    print(f"  [{idx}/{len(scan_ids)}] ⏭️  {scan_id}: Already completed - skipping")
                    skipped_count += 1
                    continue

                if status and status.get('status') not in ['not_started', 'completed']:
                    remaining = len(status.get('remaining_pages', []))
                    total = status.get('total_pages', 0)
                    completed = total - remaining
                    print(f"  [{idx}/{len(scan_ids)}] ▶️  {scan_id}: Resuming ({completed}/{total} complete)")
                else:
                    print(f"  [{idx}/{len(scan_ids)}] ▶️  {scan_id}: Will process")

            books_to_process.append(scan_id)

        except KeyboardInterrupt:
            print(f"\n\n⚠️  Interrupted during Phase 1")
            print(f"   Queued: {len(books_to_process)}, Skipped: {skipped_count}, Remaining: {len(scan_ids) - idx}")
            if args.force:
                print(f"   Note: {len(books_to_process)} books were cleaned and need processing")
            sys.exit(0)
        except Exception as e:
            print(f"  [{idx}/{len(scan_ids)}] ❌ {scan_id}: Error during Phase 1: {e}")
            continue

    if args.force:
        print(f"\nPhase 1 complete: Cleaned {len(books_to_process)} books, skipped {skipped_count}")
    else:
        print(f"\nPhase 1 complete: {len(books_to_process)} books to process, {skipped_count} skipped")

    if not books_to_process:
        print("\n✅ No books to process")
        return

    print(f"\nPhase 2: Running {args.stage} stage on {len(books_to_process)} books...\n")
    processed_count = 0

    from cli.namespace_book import cmd_run_stage

    for idx, scan_id in enumerate(books_to_process, 1):
        print(f"\n{'='*60}")
        print(f"[{idx}/{len(books_to_process)}] Processing: {scan_id}")
        print(f"{'='*60}")

        try:
            storage = library.get_book_storage(scan_id)
            print(f"  ▶️  Running {args.stage} stage...")

            run_args = argparse.Namespace(
                scan_id=scan_id,
                stage=args.stage,
                model=getattr(args, 'model', None),
                workers=getattr(args, 'workers', None),
                clean=False
            )

            cmd_run_stage(run_args)

            print(f"  ✅ Completed: {scan_id}")
            processed_count += 1

        except KeyboardInterrupt:
            print(f"\n\n⚠️  Interrupted by user. Stopping...")
            print(f"   Processed: {processed_count}, Skipped: {skipped_count}, Remaining: {len(books_to_process) - idx}")
            print(f"   Note: Run without --force to continue from where you left off")
            sys.exit(0)
        except Exception as e:
            print(f"  ❌ Error processing {scan_id}: {e}")
            print(f"     Continuing to next book...")
            continue

    print(f"\n{'='*60}")
    print(f"✅ Sweep complete:")
    print(f"   Processed: {processed_count}, Skipped: {skipped_count}, Total: {len(scan_ids)}")
    print(f"{'='*60}\n")


def setup_batch_parser(subparsers):
    batch_parser = subparsers.add_parser('batch', help='Run stage across all books in library')
    batch_parser.add_argument('stage', choices=CORE_STAGES, help='Stage to run')
    batch_parser.add_argument('--model', help='Vision model (for correction/label stages)')
    batch_parser.add_argument('--workers', type=int, default=None, help='Parallel workers')
    batch_parser.add_argument('--reshuffle', action='store_true', help='Create new random order')
    batch_parser.add_argument('--force', action='store_true', help='Regenerate even if completed')
    batch_parser.set_defaults(func=cmd_batch)
