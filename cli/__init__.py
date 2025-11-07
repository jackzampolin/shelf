import argparse
import cli.library
import cli.book
from cli.batch import setup_batch_parser
from cli.serve import setup_serve_parser


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
  shelf book modest-lovelace info --stage tesseract
  shelf book modest-lovelace report --stage label-pages --filter "printed_page_number="
  shelf book modest-lovelace run-stage tesseract
  shelf book modest-lovelace run-stage ocr-pages --workers 20
  shelf book modest-lovelace process
  shelf book modest-lovelace process --clean
  shelf book modest-lovelace clean --stage tesseract

  # Library-wide batch operations
  shelf batch label-pages
  shelf batch ocr-pages --delete-outputs --yes

  # Web frontend
  shelf serve
  shelf serve --port 8080 --host 0.0.0.0
"""
    )

    subparsers = parser.add_subparsers(dest='command', help='Command namespace')
    subparsers.required = True

    cli.library.setup_parser(subparsers)
    cli.book.setup_parser(subparsers)
    setup_batch_parser(subparsers)
    setup_serve_parser(subparsers)

    return parser


def main():
    parser = create_parser()
    args = parser.parse_args()
    args.func(args)
