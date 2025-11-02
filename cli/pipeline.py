import sys

from infra.storage.library import Library
from infra.pipeline.runner import run_stage, run_pipeline
from infra.config import Config
from cli.constants import CORE_STAGES


def cmd_process(args):
    from pipeline.ocr import OCRStage
    from pipeline.paragraph_correct import ParagraphCorrectStage
    from pipeline.label_pages import LabelPagesStage
    from pipeline.merged import MergeStage

    library = Library(storage_root=Config.book_storage_root)
    scan = library.get_scan_info(args.scan_id)

    if not scan:
        print(f"❌ Book not found: {args.scan_id}")
        sys.exit(1)

    storage = library.get_book_storage(args.scan_id)

    if args.stage:
        stages_to_run = [args.stage]
    elif args.stages:
        stages_to_run = [s.strip() for s in args.stages.split(',')]
    else:
        stages_to_run = CORE_STAGES

    stage_map = {
        'ocr': OCRStage(max_workers=args.workers if args.workers else None),
        'paragraph-correct': ParagraphCorrectStage(
            model=args.model,
            max_workers=args.workers if args.workers else 30,
            max_retries=3
        ),
        'label-pages': LabelPagesStage(
            model=args.model,
            max_workers=args.workers if args.workers else 30,
            max_retries=3
        ),
        'merged': MergeStage(max_workers=args.workers if args.workers else 8)
    }

    for stage_name in stages_to_run:
        if stage_name not in stage_map:
            print(f"❌ Unknown stage: {stage_name}")
            print(f"   Valid stages: {', '.join(stage_map.keys())}")
            sys.exit(1)

    if args.clean:
        from cli.helpers import clean_stage_directory
        print(f"\n🧹 Cleaning stages before processing: {', '.join(stages_to_run)}")
        for stage_name in stages_to_run:
            clean_stage_directory(storage, stage_name)
            print(f"   ✓ Cleaned {stage_name}")
        print()

    stages = [stage_map[name] for name in stages_to_run]

    try:
        if len(stages) == 1:
            print(f"\n🔧 Running stage: {stages[0].name}")
            stats = run_stage(stages[0], storage)
            print(f"\n✅ Stage complete: {stages[0].name}")
        else:
            print(f"\n🔧 Running pipeline: {', '.join(s.name for s in stages)}")
            results = run_pipeline(stages, storage, stop_on_error=True)
            print(f"\n✅ Pipeline complete: {len(results)} stages")
    except Exception as e:
        print(f"\n❌ Pipeline failed: {e}")
        sys.exit(1)


def cmd_clean(args):
    from cli.helpers import clean_stage_directory

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
