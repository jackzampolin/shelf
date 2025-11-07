import sys
import json

from infra.pipeline.storage.library import Library
from infra.config import Config
from cli.helpers import get_stage_status, get_stage_and_status
from cli.constants import CORE_STAGES


def cmd_info(args):
    library = Library(storage_root=Config.book_storage_root)
    scan = library.get_scan_info(args.scan_id)

    if not scan:
        print(f"❌ Book not found: {args.scan_id}")
        sys.exit(1)

    storage = library.get_book_storage(args.scan_id)

    if args.json:
        if args.stage:
            status = get_stage_status(storage, args.stage)
            if status is None:
                print(f"❌ Unknown stage: {args.stage}")
                sys.exit(1)
            print(json.dumps(status, indent=2))
        else:
            all_status = {'metadata': scan, 'stages': {}}
            for stage_name in CORE_STAGES:
                status = get_stage_status(storage, stage_name)
                if status:
                    all_status['stages'][stage_name] = status
            print(json.dumps(all_status, indent=2))
        return

    if args.stage:
        stage, status = get_stage_and_status(storage, args.stage)
        if status is None:
            print(f"❌ Unknown stage: {args.stage}")
            print(f"Available stages: {', '.join(CORE_STAGES)}")
            sys.exit(1)

        stage_status = status.get('status', 'unknown')
        if stage_status == 'completed':
            symbol = '✅'
        elif stage_status in ['not_started']:
            symbol = '○'
        elif stage_status == 'failed':
            symbol = '❌'
        else:
            symbol = '⏳'

        print(f"\n{symbol} {args.stage}")
        print(stage.pretty_print_status(status))
        print()
        return

    print(f"\n📖 {scan['title']}")
    print("=" * 80)
    print(f"Scan ID:     {scan['scan']['scan_id']}")
    print(f"Author:      {scan.get('author', 'Unknown')}")
    print(f"Publisher:   {scan.get('publisher', 'Unknown')}")
    print(f"Year:        {scan.get('year', 'Unknown')}")
    print(f"Pages:       {scan['scan'].get('pages', 'Unknown')}")
    print(f"Status:      {scan['scan'].get('status', 'unknown')}")

    if scan['scan'].get('cost_usd'):
        print(f"Cost:        ${scan['scan']['cost_usd']:.2f}")

    print(f"\n📊 Pipeline Status")
    print("=" * 80)

    total_cost = 0.0

    for stage_name in CORE_STAGES:
        stage, status = get_stage_and_status(storage, stage_name)

        if status is None:
            print(f"\n? {stage_name}")
            print(f"   Status: unknown")
            continue

        stage_status = status.get('status', 'not_started')

        if stage_status == 'completed':
            symbol = '✅'
        elif stage_status in ['not_started']:
            symbol = '○'
        elif stage_status == 'failed':
            symbol = '❌'
        else:
            symbol = '⏳'

        print(f"\n{symbol} {stage_name}")
        print(stage.pretty_print_status(status))

        metrics = status.get('metrics', {})
        stage_cost = metrics.get('total_cost_usd', 0)
        total_cost += stage_cost

    if total_cost > 0:
        print(f"\n💰 Total Pipeline Cost: ${total_cost:.2f}")
    print()
