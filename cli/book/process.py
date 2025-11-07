import sys

from infra.pipeline.storage.library import Library
from infra.pipeline.runner import run_stage
from infra.config import Config
from cli.helpers import clean_stage_directory
from cli.constants import CORE_STAGES


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

    print(f"\n🔧 Running pipeline: {', '.join(s.name for s in stages)}")

    try:
        for i, stage in enumerate(stages, 1):
            print(f"[{i}/{len(stages)}] {stage.name}")
            run_stage(stage)
            print(f"✅ {stage.name} complete")

        print(f"\n✅ Pipeline complete: {len(stages)} stages")
    except Exception as e:
        print(f"❌ Pipeline failed: {e}")
        sys.exit(1)
