import sys
import shutil

from infra.storage.library import Library
from infra.pipeline.runner import run_stage, run_pipeline
from infra.config import Config


def clean_stage_helper(storage, stage_name):
    stage_storage = storage.stage(stage_name)

    if stage_storage.output_dir.exists():
        for item in stage_storage.output_dir.iterdir():
            if item.name == '.gitkeep':
                continue
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)

    checkpoint = stage_storage.checkpoint
    checkpoint.reset(confirm=False)


def cmd_analyze(args):
    from pipeline.label_pages import LabelPagesStage
    from pipeline.paragraph_correct import ParagraphCorrectStage

    library = Library(storage_root=Config.book_storage_root)
    scan = library.get_scan_info(args.scan_id)

    if not scan:
        print(f"❌ Book not found: {args.scan_id}")
        sys.exit(1)

    storage = library.get_book_storage(args.scan_id)
    stage_storage = storage.stage(args.stage)
    report_path = stage_storage.output_dir / "report.csv"

    if not report_path.exists():
        print(f"❌ No report found for {args.stage} stage")
        print(f"   Run: shelf process {args.scan_id} --stage {args.stage}")
        sys.exit(1)

    stage_classes = {
        'label-pages': LabelPagesStage,
        'paragraph-correct': ParagraphCorrectStage,
    }

    stage_class = stage_classes[args.stage]

    print(f"\n🔍 Analyzing {args.stage} stage for {args.scan_id}...")
    if args.model:
        print(f"   Model: {args.model}")
    else:
        print(f"   Model: {Config.text_model_primary} (default)")

    if args.focus:
        print(f"   Focus areas: {', '.join(args.focus)}")

    try:
        result = stage_class.analyze(
            storage=storage,
            model=args.model,
            focus_areas=args.focus
        )

        print(f"\n✅ Analysis complete!")
        print(f"   Report: {result['analysis_path']}")
        print(f"   Tool calls: {result['tool_calls_path']}")
        print(f"   Cost: ${result['cost_usd']:.4f}")
        print(f"   Iterations: {result['iterations']}")
        print(f"   Run hash: {result['run_hash']}")
    except Exception as e:
        print(f"\n❌ Analysis failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def cmd_process(args):
    from pipeline.ocr import OCRStage
    from pipeline.paragraph_correct import ParagraphCorrectStage
    from pipeline.label_pages import LabelPagesStage
    from pipeline.merged import MergeStage
    from pipeline.build_structure import BuildStructureStage

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
        stages_to_run = ['ocr', 'paragraph-correct', 'label-pages', 'merged']

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
        'merged': MergeStage(max_workers=args.workers if args.workers else 8),
        'build_structure': BuildStructureStage(model=args.model)
    }

    for stage_name in stages_to_run:
        if stage_name not in stage_map:
            print(f"❌ Unknown stage: {stage_name}")
            print(f"   Valid stages: {', '.join(stage_map.keys())}")
            sys.exit(1)

    if args.clean:
        print(f"\n🧹 Cleaning stages before processing: {', '.join(stages_to_run)}")
        for stage_name in stages_to_run:
            clean_stage_helper(storage, stage_name)
            print(f"   ✓ Cleaned {stage_name}")
        print()

    stages = [stage_map[name] for name in stages_to_run]

    try:
        if len(stages) == 1:
            print(f"\n🔧 Running stage: {stages[0].name}")
            stats = run_stage(stages[0], storage, resume=True)
            print(f"\n✅ Stage complete: {stages[0].name}")
        else:
            print(f"\n🔧 Running pipeline: {', '.join(s.name for s in stages)}")
            results = run_pipeline(stages, storage, resume=True, stop_on_error=True)
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
        if stage_storage.output_dir.exists():
            for item in stage_storage.output_dir.iterdir():
                if item.name == '.gitkeep':
                    continue
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)

        checkpoint = stage_storage.checkpoint
        checkpoint.reset(confirm=False)

        print(f"\n✅ Cleaned stage: {args.stage}")
        print(f"   Deleted all outputs from: {stage_storage.output_dir}")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
