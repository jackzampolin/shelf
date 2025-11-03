import sys
import argparse

from infra.storage.library import Library
from infra.config import Config
from cli.helpers import get_stage_status, clean_stage_directory
from cli.constants import REPORT_STAGES


def sweep_stage(library, args):
    scan_ids = library.create_shuffle(reshuffle=args.reshuffle)
    shuffle_info = library.get_shuffle_info()

    if args.reshuffle:
        print(f"🔀 Created new global shuffle order")
    elif shuffle_info:
        created_date = shuffle_info.get('created_at', '')[:10] if 'created_at' in shuffle_info else 'unknown'
        print(f"♻️  Using existing global shuffle order (created: {created_date})")
    else:
        print(f"🎲 Created random order")

    print(f"\n🧹 Sweeping '{args.target}' stage across {len(scan_ids)} books")
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
                print(f"  [{idx}/{len(scan_ids)}] 🧹 {scan_id}: Cleaning {args.target} stage...")
                clean_stage_directory(storage, args.target)
            else:
                status = get_stage_status(storage, args.target)
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

    print(f"\nPhase 2: Running {args.target} stage on {len(books_to_process)} books...\n")
    processed_count = 0

    from cli.pipeline import cmd_process

    for idx, scan_id in enumerate(books_to_process, 1):
        print(f"\n{'='*60}")
        print(f"[{idx}/{len(books_to_process)}] Processing: {scan_id}")
        print(f"{'='*60}")

        try:
            storage = library.get_book_storage(scan_id)
            print(f"  ▶️  Running {args.target} stage...")

            process_args = argparse.Namespace(
                scan_id=scan_id,
                stage=args.target,
                stages=None,
                model=getattr(args, 'model', None),
                workers=getattr(args, 'workers', None),
                clean=False
            )

            cmd_process(process_args)

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


def sweep_reports(library, args):
    from infra.pipeline.logger import PipelineLogger
    from pipeline.ocr import OCRStage
    from pipeline.paragraph_correct import ParagraphCorrectStage
    from pipeline.label_pages import LabelPagesStage

    all_books = library.list_books()
    print(f"📚 Sweeping reports across {len(all_books)} books")

    stage_map = {
        'ocr': OCRStage(),
        'paragraph-correct': ParagraphCorrectStage(),
        'label-pages': LabelPagesStage()
    }

    if hasattr(args, 'stage_filter') and args.stage_filter:
        stages_to_process = [args.stage_filter]
    else:
        stages_to_process = list(REPORT_STAGES)

    total_regenerated = 0

    for book in all_books:
        scan_id = book['scan_id']
        storage = library.get_book_storage(scan_id)

        for stage_name in stages_to_process:
            stage = stage_map.get(stage_name)
            if not stage:
                print(f"⚠️  Unknown stage: {stage_name}")
                continue

            stage_storage = storage.stage(stage_name)

            if stage_name == 'ocr':
                # OCR stage uses multiple PSM (Page Segmentation Mode) configurations.
                # Only regenerate report if at least one PSM checkpoint exists.
                ocr_dir = stage_storage.output_dir
                has_psm_data = False
                for psm in [3, 4, 6]:
                    psm_checkpoint_file = ocr_dir / f'psm{psm}' / '.checkpoint'
                    if psm_checkpoint_file.exists():
                        has_psm_data = True
                        break
                if not has_psm_data:
                    continue
            else:
                all_metrics = stage_storage.metrics_manager.get_all()
                if not all_metrics:
                    continue

            try:
                logger = PipelineLogger(scan_id=scan_id, stage=stage_name)

                if stage_name == 'ocr':
                    metadata = storage.load_metadata()
                    total_pages = metadata.get('total_pages', 0)
                    stats = {'pages_processed': total_pages}
                    stage.after(storage, logger, stats)
                    total_regenerated += 1
                    print(f"✅ {scan_id}/{stage_name}/ (report.csv + psm_selection.json + psm reports)")
                else:
                    report_path = stage.generate_report(storage, logger)
                    if report_path:
                        total_regenerated += 1
                        all_metrics = stage_storage.metrics_manager.get_all()
                        print(f"✅ {scan_id}/{stage_name}/report.csv ({len(all_metrics)} pages)")
            except Exception as e:
                print(f"❌ Failed to regenerate {scan_id}/{stage_name}: {e}")

    print(f"\n✅ Regenerated {total_regenerated} reports across {len(all_books)} books\n")


def cmd_sweep(args):
    library = Library(storage_root=Config.book_storage_root)

    if args.target == 'reports':
        sweep_reports(library, args)
    else:
        sweep_stage(library, args)
