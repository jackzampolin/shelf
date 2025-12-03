"""Phase-level command handlers."""
import sys
import json

from infra.pipeline.storage.library import Library
from infra.pipeline.registry import get_stage_instance
from infra.config import Config
from cli.helpers import list_stage_phases, clean_stage_phase
from infra.pipeline.status.multi_phase import MultiPhaseStatusTracker
from infra.pipeline.status.phase_tracker import PhaseStatusTracker


def cmd_phase_info(args):
    """Show phase status and info."""
    library = Library(storage_root=Config.book_storage_root)
    scan = library.get_scan_info(args.scan_id)

    if not scan:
        print(f"Book not found: {args.scan_id}")
        sys.exit(1)

    storage = library.get_book_storage(args.scan_id)

    # Validate phase exists
    phases = list_stage_phases(storage, args.stage_name)
    if args.phase_name not in phases:
        print(f"Phase '{args.phase_name}' not found in stage '{args.stage_name}'")
        print(f"   Available phases: {', '.join(phases)}")
        sys.exit(1)

    # Get phase tracker and status
    stage = get_stage_instance(storage, args.stage_name)
    try:
        tracker = stage.status_tracker

        phase_tracker = None
        if isinstance(tracker, MultiPhaseStatusTracker):
            phase_tracker = tracker.get_phase_tracker(args.phase_name)
        elif isinstance(tracker, PhaseStatusTracker):
            if tracker.phase_name == args.phase_name:
                phase_tracker = tracker

        if phase_tracker is None:
            print(f"Phase '{args.phase_name}' not found")
            sys.exit(1)

        status = phase_tracker.get_status(metrics=True)

        if args.json:
            print(json.dumps(status, indent=2))
            return

        phase_status = status.get('status', 'unknown')
        if phase_status == 'completed':
            symbol = '[done]'
        elif phase_status in ['not_started']:
            symbol = '[    ]'
        else:
            symbol = '[....]'

        progress = status.get('progress', {})
        total = progress.get('total_items', 0)
        completed = progress.get('completed_items', 0)
        remaining = progress.get('remaining_items', [])

        print(f"\n{symbol} {args.stage_name}.{args.phase_name}")
        print(f"   Status: {phase_status}")
        print(f"   Progress: {completed}/{total} items")

        if remaining and len(remaining) <= 10:
            print(f"   Remaining: {remaining}")
        elif remaining:
            print(f"   Remaining: {len(remaining)} items")

        metrics = status.get('metrics', {})
        if metrics:
            cost = metrics.get('total_cost_usd', 0)
            if cost > 0:
                print(f"   Cost: ${cost:.4f}")

        print()
    finally:
        stage.logger.close()


def cmd_phase_clean(args):
    """Clean phase outputs."""
    library = Library(storage_root=Config.book_storage_root)
    scan = library.get_scan_info(args.scan_id)

    if not scan:
        print(f"Book not found: {args.scan_id}")
        sys.exit(1)

    storage = library.get_book_storage(args.scan_id)

    # Validate phase exists
    phases = list_stage_phases(storage, args.stage_name)
    if args.phase_name not in phases:
        print(f"Phase '{args.phase_name}' not found in stage '{args.stage_name}'")
        print(f"   Available phases: {', '.join(phases)}")
        sys.exit(1)

    if not args.yes:
        print(f"\nWARNING: This will delete outputs for:")
        print(f"   Book:  {args.scan_id}")
        print(f"   Stage: {args.stage_name}")
        print(f"   Phase: {args.phase_name}")

        try:
            response = input("\nAre you sure? (yes/no): ").strip().lower()
            if response not in ['yes', 'y']:
                print("Cancelled.")
                return
        except EOFError:
            print("\nCancelled (no input)")
            return

    try:
        result = clean_stage_phase(storage, args.stage_name, args.phase_name)
        print(f"\nCleaned phase: {args.stage_name}.{args.phase_name}")
        print(f"   Deleted {result['deleted_count']} files")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
