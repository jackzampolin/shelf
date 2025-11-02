import argparse
from cli.library import (
    cmd_shelve, cmd_list, cmd_show, cmd_status, cmd_stage_status,
    cmd_report, cmd_stats, cmd_delete
)
from cli.pipeline import cmd_analyze, cmd_process, cmd_clean
from cli.sweep import cmd_sweep


def create_parser():
    parser = argparse.ArgumentParser(
        prog='shelf',
        description='Scanshelf - Turn physical books into digital libraries',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Library management
  shelf shelve ~/Documents/Scans/book.pdf
  shelf shelve ~/Documents/Scans/*.pdf --run-ocr
  shelf list
  shelf stats
  shelf delete old-book --yes

  # Single book operations
  shelf show modest-lovelace
  shelf status modest-lovelace
  shelf report modest-lovelace --stage paragraph-correct
  shelf report modest-lovelace --stage label-pages --filter "printed_page_number="
  shelf analyze modest-lovelace --stage label-pages
  shelf process modest-lovelace
  shelf process modest-lovelace --stage ocr
  shelf clean modest-lovelace --stage ocr

  # Library-wide sweeps
  shelf sweep label-pages                    # Run label-pages stage across all books
  shelf sweep label-pages --reshuffle        # Create new random order
  shelf sweep paragraph-correct --force         # Regenerate even if completed
  shelf sweep reports                   # Regenerate all reports from checkpoints
  shelf sweep reports --stage-filter label-pages  # Only regenerate label-pages reports
"""
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    subparsers.required = True

    # Library commands
    shelve_parser = subparsers.add_parser('shelve', help='Shelve book(s) into library')
    shelve_parser.add_argument('pdf_patterns', nargs='+', help='PDF file pattern(s)')
    shelve_parser.add_argument('--run-ocr', action='store_true', help='Run OCR after shelving')
    shelve_parser.set_defaults(func=cmd_shelve)

    list_parser = subparsers.add_parser('list', help='List all books')
    list_parser.set_defaults(func=cmd_list)

    show_parser = subparsers.add_parser('show', help='Show book details')
    show_parser.add_argument('scan_id', help='Book scan ID')
    show_parser.set_defaults(func=cmd_show)

    status_parser = subparsers.add_parser('status', help='Show pipeline status')
    status_parser.add_argument('scan_id', help='Book scan ID')
    status_parser.set_defaults(func=cmd_status)

    stage_status_parser = subparsers.add_parser('stage-status', help='Show detailed stage status (for debugging)')
    stage_status_parser.add_argument('scan_id', help='Book scan ID')
    stage_status_parser.add_argument('--stage', required=True, help='Stage name')
    stage_status_parser.set_defaults(func=cmd_stage_status)

    report_parser = subparsers.add_parser('report', help='Display stage report as table')
    report_parser.add_argument('scan_id', help='Book scan ID')
    report_parser.add_argument('--stage', required=True, choices=['ocr', 'paragraph-correct', 'label-pages'], help='Stage to show report for')
    report_parser.add_argument('--limit', type=int, help='Number of rows to show (default: 20)')
    report_parser.add_argument('--all', '-a', action='store_true', help='Show all rows')
    report_parser.add_argument('--filter', help='Filter rows (e.g., "total_corrections>0")')
    report_parser.set_defaults(func=cmd_report)

    analyze_parser = subparsers.add_parser('analyze', help='Analyze stage outputs with AI agent')
    analyze_parser.add_argument('scan_id', help='Book scan ID')
    analyze_parser.add_argument('--stage', required=True, choices=['label-pages', 'paragraph-correct'], help='Stage to analyze')
    analyze_parser.add_argument('--model', help='OpenRouter model (default: Config.text_model_primary)')
    analyze_parser.add_argument('--focus', nargs='+', help='Focus areas (e.g., page_numbers regions)')
    analyze_parser.set_defaults(func=cmd_analyze)

    stats_parser = subparsers.add_parser('stats', help='Library statistics')
    stats_parser.set_defaults(func=cmd_stats)

    delete_parser = subparsers.add_parser('delete', help='Delete book from library')
    delete_parser.add_argument('scan_id', help='Book scan ID')
    delete_parser.add_argument('-y', '--yes', action='store_true', help='Skip confirmation')
    delete_parser.add_argument('--keep-files', action='store_true', help='Keep files (only remove from library)')
    delete_parser.set_defaults(func=cmd_delete)

    # Pipeline commands
    process_parser = subparsers.add_parser('process', help='Run pipeline stages (auto-resume)')
    process_parser.add_argument('scan_id', help='Book scan ID')
    process_parser.add_argument('--stage', choices=['ocr', 'paragraph-correct', 'label-pages', 'merged', 'build_structure'], help='Single stage to run')
    process_parser.add_argument('--stages', help='Multiple stages (comma-separated)')
    process_parser.add_argument('--model', help='Vision model (for correction/label stages)')
    process_parser.add_argument('--workers', type=int, default=None, help='Parallel workers')
    process_parser.add_argument('--clean', action='store_true', help='Clean stages before processing (start fresh)')
    process_parser.add_argument('--auto-analyze', action='store_true', dest='auto_analyze', help='Enable automatic stage analysis (disabled by default)')
    process_parser.set_defaults(func=cmd_process, auto_analyze=False)

    clean_parser = subparsers.add_parser('clean', help='Clean stage outputs')
    clean_parser.add_argument('scan_id', help='Book scan ID')
    clean_parser.add_argument('--stage', required=True, choices=['ocr', 'paragraph-correct', 'label-pages', 'merged'], help='Stage to clean')
    clean_parser.add_argument('-y', '--yes', action='store_true', help='Skip confirmation')
    clean_parser.set_defaults(func=cmd_clean)

    # Sweep command
    sweep_parser = subparsers.add_parser('sweep', help='Sweep through library: run stages or regenerate reports')
    sweep_parser.add_argument('target', choices=['ocr', 'paragraph-correct', 'label-pages', 'merged', 'build_structure', 'reports'], help='What to sweep: stage name or "reports"')
    sweep_parser.add_argument('--model', help='Vision model (for correction/label stages)')
    sweep_parser.add_argument('--workers', type=int, default=None, help='Parallel workers')
    sweep_parser.add_argument('--reshuffle', action='store_true', help='Create new random order (stages only)')
    sweep_parser.add_argument('--force', action='store_true', help='Regenerate even if completed (stages only)')
    sweep_parser.add_argument('--stage-filter', choices=['ocr', 'paragraph-correct', 'label-pages'], help='Filter which stage reports to regenerate (reports only)')
    sweep_parser.set_defaults(func=cmd_sweep)

    return parser


def main():
    parser = create_parser()
    args = parser.parse_args()
    args.func(args)
