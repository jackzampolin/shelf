"""Book CLI commands with hierarchical stage/phase structure."""
from cli.book.info import cmd_info
from cli.book.process import cmd_process
from cli.book.stage import cmd_stage_run, cmd_stage_info, cmd_stage_clean, cmd_stage_report
from cli.book.phase import cmd_phase_info, cmd_phase_clean
from cli.book.config import cmd_book_config_show, cmd_book_config_set, cmd_book_config_clear
from cli.constants import CORE_STAGES, REPORT_STAGES


def setup_parser(subparsers):
    """Setup book command parser with hierarchical stage/phase structure."""
    book_parser = subparsers.add_parser('book', help='Single book operations')
    book_parser.add_argument('scan_id', help='Book scan ID')

    book_subparsers = book_parser.add_subparsers(dest='book_command', help='Book command')
    book_subparsers.required = True

    # =========================================================================
    # Book-level commands
    # =========================================================================

    # book info
    info_parser = book_subparsers.add_parser('info', help='Show book metadata and pipeline status')
    info_parser.add_argument('--json', action='store_true', help='Output as JSON')
    info_parser.set_defaults(func=cmd_info)

    # book process
    process_parser = book_subparsers.add_parser('process', help='Run all pipeline stages')
    process_parser.add_argument('--model', help='Vision model (for correction/label stages)')
    process_parser.add_argument('--workers', type=int, default=None, help='Parallel workers')
    process_parser.add_argument('--delete-outputs', action='store_true', help='DELETE all stage outputs before processing (WARNING: irreversible)')
    process_parser.set_defaults(func=cmd_process)

    # =========================================================================
    # Book config commands: book <id> config <action>
    # =========================================================================

    config_parser = book_subparsers.add_parser('config', help='Book configuration overrides')
    config_subparsers = config_parser.add_subparsers(dest='config_command', help='Config command')
    config_subparsers.required = True

    # book <id> config show
    config_show_parser = config_subparsers.add_parser('show', help='Show book configuration')
    config_show_parser.add_argument('--json', action='store_true', help='Output as JSON')
    config_show_parser.set_defaults(func=cmd_book_config_show)

    # book <id> config set <key> <value>
    config_set_parser = config_subparsers.add_parser('set', help='Set book configuration')
    config_set_parser.add_argument('key', help='Config key (ocr_providers, blend_model, max_workers)')
    config_set_parser.add_argument('value', help='Value to set')
    config_set_parser.set_defaults(func=cmd_book_config_set)

    # book <id> config clear
    config_clear_parser = config_subparsers.add_parser('clear', help='Clear book overrides')
    config_clear_parser.add_argument('-y', '--yes', action='store_true', help='Skip confirmation')
    config_clear_parser.set_defaults(func=cmd_book_config_clear)

    # =========================================================================
    # Stage-level commands: book <id> stage <name> <action>
    # =========================================================================

    stage_parser = book_subparsers.add_parser('stage', help='Stage operations')
    stage_parser.add_argument('stage_name', choices=CORE_STAGES, help='Stage name')

    stage_subparsers = stage_parser.add_subparsers(dest='stage_command', help='Stage command')
    stage_subparsers.required = True

    # book <id> stage <name> run
    stage_run_parser = stage_subparsers.add_parser('run', help='Run the stage')
    stage_run_parser.add_argument('--model', help='Vision model (for correction/label stages)')
    stage_run_parser.add_argument('--workers', type=int, default=None, help='Parallel workers')
    stage_run_parser.add_argument('--delete-outputs', action='store_true', help='DELETE stage outputs before processing')
    stage_run_parser.set_defaults(func=cmd_stage_run)

    # book <id> stage <name> info (aliased as status)
    stage_info_parser = stage_subparsers.add_parser('info', help='Show stage status', aliases=['status'])
    stage_info_parser.add_argument('--json', action='store_true', help='Output as JSON')
    stage_info_parser.set_defaults(func=cmd_stage_info)

    # book <id> stage <name> clean
    stage_clean_parser = stage_subparsers.add_parser('clean', help='Clean stage outputs')
    stage_clean_parser.add_argument('-y', '--yes', action='store_true', help='Skip confirmation')
    stage_clean_parser.set_defaults(func=cmd_stage_clean)

    # book <id> stage <name> report
    stage_report_parser = stage_subparsers.add_parser('report', help='Display stage report')
    stage_report_parser.add_argument('--limit', type=int, help='Number of rows to show (default: 20)')
    stage_report_parser.add_argument('--all', '-a', action='store_true', help='Show all rows')
    stage_report_parser.add_argument('--filter', help='Filter rows (e.g., "page_num=5")')
    stage_report_parser.set_defaults(func=cmd_stage_report)

    # book <id> stage <name> phase <phase> <action>
    phase_parser = stage_subparsers.add_parser('phase', help='Phase operations')
    phase_parser.add_argument('phase_name', help='Phase name')

    phase_subparsers = phase_parser.add_subparsers(dest='phase_command', help='Phase command')
    phase_subparsers.required = True

    # book <id> stage <name> phase <phase> info (aliased as status)
    phase_info_parser = phase_subparsers.add_parser('info', help='Show phase status', aliases=['status'])
    phase_info_parser.add_argument('--json', action='store_true', help='Output as JSON')
    phase_info_parser.set_defaults(func=cmd_phase_info)

    # book <id> stage <name> phase <phase> clean
    phase_clean_parser = phase_subparsers.add_parser('clean', help='Clean phase outputs')
    phase_clean_parser.add_argument('-y', '--yes', action='store_true', help='Skip confirmation')
    phase_clean_parser.set_defaults(func=cmd_phase_clean)


__all__ = [
    'cmd_info',
    'cmd_process',
    'cmd_stage_run',
    'cmd_stage_info',
    'cmd_stage_clean',
    'cmd_stage_report',
    'cmd_phase_info',
    'cmd_phase_clean',
    'cmd_book_config_show',
    'cmd_book_config_set',
    'cmd_book_config_clear',
    'setup_parser',
]
