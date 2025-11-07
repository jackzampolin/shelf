from cli.book.info import cmd_info
from cli.book.report import cmd_report
from cli.book.run_stage import cmd_run_stage
from cli.book.process import cmd_process
from cli.book.clean import cmd_clean
from cli.constants import CORE_STAGES, REPORT_STAGES


def setup_parser(subparsers):
    """Setup book command parser."""
    book_parser = subparsers.add_parser('book', help='Single book operations')
    book_parser.add_argument('scan_id', help='Book scan ID')

    book_subparsers = book_parser.add_subparsers(dest='book_command', help='Book command')
    book_subparsers.required = True

    info_parser = book_subparsers.add_parser('info', help='Show book metadata and pipeline status')
    info_parser.add_argument('--stage', choices=CORE_STAGES, help='Show detailed status for one stage')
    info_parser.add_argument('--json', action='store_true', help='Output as JSON')
    info_parser.set_defaults(func=cmd_info)

    report_parser = book_subparsers.add_parser('report', help='Display stage report as table')
    report_parser.add_argument('--stage', required=True, choices=REPORT_STAGES, help='Stage to show report for')
    report_parser.add_argument('--limit', type=int, help='Number of rows to show (default: 20)')
    report_parser.add_argument('--all', '-a', action='store_true', help='Show all rows')
    report_parser.add_argument('--filter', help='Filter rows (e.g., "page_num=5" or "total_corrections>10"). Operators: = > < >= <=')
    report_parser.set_defaults(func=cmd_report)

    run_stage_parser = book_subparsers.add_parser('run-stage', help='Run a single pipeline stage')
    run_stage_parser.add_argument('stage', choices=CORE_STAGES, help='Stage to run')
    run_stage_parser.add_argument('--model', help='Vision model (for correction/label stages)')
    run_stage_parser.add_argument('--workers', type=int, default=None, help='Parallel workers')
    run_stage_parser.add_argument('--clean', action='store_true', help='DELETE stage outputs before processing (WARNING: irreversible)')
    run_stage_parser.set_defaults(func=cmd_run_stage)

    process_parser = book_subparsers.add_parser('process', help='Run all pipeline stages')
    process_parser.add_argument('--model', help='Vision model (for correction/label stages)')
    process_parser.add_argument('--workers', type=int, default=None, help='Parallel workers')
    process_parser.add_argument('--clean', action='store_true', help='DELETE all stage outputs before processing (WARNING: irreversible)')
    process_parser.set_defaults(func=cmd_process)

    clean_parser = book_subparsers.add_parser('clean', help='Clean stage outputs')
    clean_parser.add_argument('--stage', required=True, choices=CORE_STAGES, help='Stage to clean')
    clean_parser.add_argument('-y', '--yes', action='store_true', help='Skip confirmation')
    clean_parser.set_defaults(func=cmd_clean)


__all__ = ['cmd_info', 'cmd_report', 'cmd_run_stage', 'cmd_process', 'cmd_clean', 'setup_parser']
