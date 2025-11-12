import sys

from infra.pipeline.storage.library import Library
from infra.pipeline.runner import run_stage
from infra.config import Config
from cli.helpers import clean_stage_directory
from cli.constants import get_stage_map


def cmd_run_stage(args):
    library = Library(storage_root=Config.book_storage_root)
    scan = library.get_scan_info(args.scan_id)

    if not scan:
        print(f"❌ Book not found: {args.scan_id}")
        sys.exit(1)

    storage = library.get_book_storage(args.scan_id)

    # Clean BEFORE creating stage instance (which creates logger)
    if args.clean:
        print(f"\n🧹 Cleaning stage before processing: {args.stage}")
        clean_stage_directory(storage, args.stage)
        print(f"   ✓ Cleaned {args.stage}\n")

    # Create stage instances AFTER clean
    stage_map = get_stage_map(
        storage,
        model=args.model,
        workers=args.workers,
        max_retries=3
    )

    if args.stage not in stage_map:
        print(f"❌ Unknown stage: {args.stage}")
        print(f"   Valid stages: {', '.join(stage_map.keys())}")
        sys.exit(1)

    stage = stage_map[args.stage]

    print(f"\n🔧 Running stage: {stage.name}")

    try:
        stats = run_stage(stage)
        print(f"✅ Stage complete: {stage.name}")
    except Exception as e:
        print(f"❌ Stage failed: {e}")
        sys.exit(1)
