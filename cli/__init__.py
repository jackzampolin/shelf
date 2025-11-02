import argparse
from cli.namespace_library import setup_library_parser
from cli.namespace_book import setup_book_parser
from cli.namespace_batch import setup_batch_parser


def create_parser():
    parser = argparse.ArgumentParser(
        prog='shelf',
        description='Scanshelf - Turn physical books into digital libraries',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Library management
  shelf library add ~/Documents/Scans/book.pdf
  shelf library add ~/Documents/Scans/*.pdf --run-ocr
  shelf library list
  shelf library list --json
  shelf library stats
  shelf library delete old-book --yes

  # Single book operations
  shelf book modest-lovelace info
  shelf book modest-lovelace info --json
  shelf book modest-lovelace info --stage ocr
  shelf book modest-lovelace report --stage paragraph-correct
  shelf book modest-lovelace report --stage label-pages --filter "printed_page_number="
  shelf book modest-lovelace run-stage ocr
  shelf book modest-lovelace run-stage paragraph-correct --workers 20
  shelf book modest-lovelace process
  shelf book modest-lovelace process --clean
  shelf book modest-lovelace clean --stage ocr

  # Library-wide batch operations
  shelf batch label-pages
  shelf batch label-pages --reshuffle
  shelf batch paragraph-correct --force
"""
    )

    subparsers = parser.add_subparsers(dest='command', help='Command namespace')
    subparsers.required = True

    setup_library_parser(subparsers)
    setup_book_parser(subparsers)
    setup_batch_parser(subparsers)

    return parser


def main():
    parser = create_parser()
    args = parser.parse_args()
    args.func(args)
