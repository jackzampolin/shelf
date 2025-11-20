from cli.library.add import cmd_add
from cli.library.list import cmd_list
from cli.library.stats import cmd_stats
from cli.library.delete import cmd_delete
from cli.library.cleanup import cmd_cleanup


def setup_parser(subparsers):
    """Setup library command parser."""
    library_parser = subparsers.add_parser('library', help='Library management commands')
    library_subparsers = library_parser.add_subparsers(dest='library_command', help='Library command')
    library_subparsers.required = True

    add_parser = library_subparsers.add_parser('add', help='Add book(s) to library')
    add_parser.add_argument('pdf_patterns', nargs='+', help='PDF file pattern(s)')
    add_parser.add_argument('--run-ocr', action='store_true', help='Run OCR after adding')
    add_parser.set_defaults(func=cmd_add)

    list_parser = library_subparsers.add_parser('list', help='List all books')
    list_parser.add_argument('--json', action='store_true', help='Output as JSON')
    list_parser.add_argument('--detailed', action='store_true', help='Show per-stage cost and time breakdown')
    list_parser.set_defaults(func=cmd_list)

    stats_parser = library_subparsers.add_parser('stats', help='Library statistics')
    stats_parser.set_defaults(func=cmd_stats)

    delete_parser = library_subparsers.add_parser('delete', help='Delete book from library')
    delete_parser.add_argument('scan_id', help='Book scan ID')
    delete_parser.add_argument('-y', '--yes', action='store_true', help='Skip confirmation')
    delete_parser.set_defaults(func=cmd_delete)

    cleanup_parser = library_subparsers.add_parser('cleanup', help='Clean up deprecated stage directories')
    cleanup_parser.add_argument('--dry-run', action='store_true', help='Preview what would be cleaned without making changes')
    cleanup_parser.set_defaults(func=cmd_cleanup)


__all__ = ['cmd_add', 'cmd_list', 'cmd_stats', 'cmd_delete', 'cmd_cleanup', 'setup_parser']
