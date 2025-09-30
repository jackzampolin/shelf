#!/usr/bin/env python3
"""
AR Research CLI - Unified command-line interface for book processing

Usage:
    ar pipeline <book-slug>           # Run full pipeline
    ar scan                            # Interactive scan intake
    ar ocr <book-slug>                # OCR stage only
    ar correct <book-slug>            # Correction stage only
    ar fix <book-slug>                # Agent 4 fixes only
    ar structure <book-slug>          # Structure stage only
    ar monitor <book-slug>            # Real-time progress monitoring
    ar review <book-slug> <action>    # Review flagged pages
    ar status <book-slug>             # Quick status check

Examples:
    ar pipeline The-Accidental-President
    ar monitor The-Accidental-President
    ar status The-Accidental-President
"""

import sys
import argparse
from pathlib import Path

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))


def cmd_pipeline(args):
    """Run full pipeline or specific stages."""
    from pipeline.run import BookPipeline

    pipeline = BookPipeline(args.book_slug)
    success = pipeline.run(
        stages=args.stages,
        start_from=args.start_from,
        ocr_workers=args.ocr_workers,
        correct_model=args.correct_model,
        correct_workers=args.correct_workers,
        correct_rate_limit=args.correct_rate_limit,
        structure_model=args.structure_model
    )

    return 0 if success else 1


def cmd_scan(args):
    """Interactive scan intake."""
    from tools.scan import interactive_mode
    interactive_mode()
    return 0


def cmd_ocr(args):
    """Run OCR stage only."""
    from pipeline.ocr import BookOCRProcessor

    processor = BookOCRProcessor(max_workers=args.workers)
    processor.process_book(args.book_slug)
    return 0


def cmd_correct(args):
    """Run correction stage only."""
    from pipeline.correct import StructuredPageCorrector

    processor = StructuredPageCorrector(
        args.book_slug,
        model=args.model,
        max_workers=args.workers,
        calls_per_minute=args.rate_limit
    )
    processor.process_pages(start_page=args.start, end_page=args.end)
    return 0


def cmd_fix(args):
    """Run Agent 4 fix stage only."""
    from pipeline.fix import Agent4TargetedFix

    agent4 = Agent4TargetedFix(args.book_slug)
    agent4.process_all_flagged()
    return 0


def cmd_structure(args):
    """Run structure stage only."""
    from pipeline.structure import DeepBookStructurer

    structurer = DeepBookStructurer(args.book_slug, model=args.model)
    structurer.process_book()
    return 0


def cmd_monitor(args):
    """Real-time progress monitoring."""
    from tools.monitor import monitor_pipeline

    monitor_pipeline(args.book_slug, refresh_interval=args.refresh)
    return 0


def cmd_review(args):
    """Review flagged pages."""
    from tools.review import main as review_main

    # Construct arguments for review tool
    sys.argv = ['review.py', args.book_slug, args.action]
    if args.page:
        sys.argv.append(f'--page={args.page}')

    review_main()
    return 0


def cmd_status(args):
    """Quick status check."""
    from tools.monitor import print_status

    print_status(args.book_slug)
    return 0


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description='AR Research - Book Processing Pipeline',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # =========================================================================
    # PIPELINE command
    # =========================================================================
    pipeline_parser = subparsers.add_parser('pipeline', help='Run full processing pipeline')
    pipeline_parser.add_argument('book_slug', help='Book slug (e.g., The-Accidental-President)')
    pipeline_parser.add_argument('--stages', nargs='+',
                                choices=['ocr', 'correct', 'fix', 'structure'],
                                help='Run only specific stages')
    pipeline_parser.add_argument('--start-from', choices=['ocr', 'correct', 'fix', 'structure'],
                                help='Start from this stage')
    pipeline_parser.add_argument('--ocr-workers', type=int, default=8,
                                help='OCR parallel workers (default: 8)')
    pipeline_parser.add_argument('--correct-model', default='openai/gpt-4o-mini',
                                help='Correction model (default: openai/gpt-4o-mini)')
    pipeline_parser.add_argument('--correct-workers', type=int, default=30,
                                help='Correction parallel workers (default: 30)')
    pipeline_parser.add_argument('--correct-rate-limit', type=int, default=150,
                                help='Correction API calls/min (default: 150)')
    pipeline_parser.add_argument('--structure-model', default='anthropic/claude-sonnet-4.5',
                                help='Structure model (default: anthropic/claude-sonnet-4.5)')
    pipeline_parser.set_defaults(func=cmd_pipeline)

    # =========================================================================
    # SCAN command
    # =========================================================================
    scan_parser = subparsers.add_parser('scan', help='Interactive scan intake')
    scan_parser.set_defaults(func=cmd_scan)

    # =========================================================================
    # OCR command
    # =========================================================================
    ocr_parser = subparsers.add_parser('ocr', help='Run OCR stage only')
    ocr_parser.add_argument('book_slug', help='Book slug')
    ocr_parser.add_argument('--workers', type=int, default=8,
                           help='Parallel workers (default: 8)')
    ocr_parser.set_defaults(func=cmd_ocr)

    # =========================================================================
    # CORRECT command
    # =========================================================================
    correct_parser = subparsers.add_parser('correct', help='Run correction stage only')
    correct_parser.add_argument('book_slug', help='Book slug')
    correct_parser.add_argument('--model', default='openai/gpt-4o-mini',
                               help='Model (default: openai/gpt-4o-mini)')
    correct_parser.add_argument('--workers', type=int, default=30,
                               help='Parallel workers (default: 30)')
    correct_parser.add_argument('--rate-limit', type=int, default=150,
                               help='API calls/min (default: 150)')
    correct_parser.add_argument('--start', type=int, default=1,
                               help='Start page (default: 1)')
    correct_parser.add_argument('--end', type=int, default=None,
                               help='End page (default: all)')
    correct_parser.set_defaults(func=cmd_correct)

    # =========================================================================
    # FIX command
    # =========================================================================
    fix_parser = subparsers.add_parser('fix', help='Run Agent 4 fixes only')
    fix_parser.add_argument('book_slug', help='Book slug')
    fix_parser.set_defaults(func=cmd_fix)

    # =========================================================================
    # STRUCTURE command
    # =========================================================================
    structure_parser = subparsers.add_parser('structure', help='Run structure stage only')
    structure_parser.add_argument('book_slug', help='Book slug')
    structure_parser.add_argument('--model', default='anthropic/claude-sonnet-4.5',
                                 help='Model (default: anthropic/claude-sonnet-4.5)')
    structure_parser.set_defaults(func=cmd_structure)

    # =========================================================================
    # MONITOR command
    # =========================================================================
    monitor_parser = subparsers.add_parser('monitor', help='Real-time progress monitoring')
    monitor_parser.add_argument('book_slug', help='Book slug')
    monitor_parser.add_argument('--refresh', type=int, default=5,
                               help='Refresh interval in seconds (default: 5)')
    monitor_parser.set_defaults(func=cmd_monitor)

    # =========================================================================
    # REVIEW command
    # =========================================================================
    review_parser = subparsers.add_parser('review', help='Review flagged pages')
    review_parser.add_argument('book_slug', help='Book slug')
    review_parser.add_argument('action', choices=['report', 'checklist', 'accept'],
                              help='Action to perform')
    review_parser.add_argument('--page', type=int, help='Specific page to review')
    review_parser.set_defaults(func=cmd_review)

    # =========================================================================
    # STATUS command
    # =========================================================================
    status_parser = subparsers.add_parser('status', help='Quick status check')
    status_parser.add_argument('book_slug', help='Book slug')
    status_parser.set_defaults(func=cmd_status)

    # Parse and execute
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    try:
        return args.func(args)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
