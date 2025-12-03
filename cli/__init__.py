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

  # Book operations
  shelf book my-book info
  shelf book my-book info --json
  shelf book my-book process
  shelf book my-book process --delete-outputs

  # Stage operations
  shelf book my-book stage ocr-pages run --workers 20
  shelf book my-book stage ocr-pages info
  shelf book my-book stage ocr-pages clean -y
  shelf book my-book stage label-structure report --filter "page_num=5"

  # Phase operations (granular control within a stage)
  shelf book my-book stage ocr-pages phase blend info
  shelf book my-book stage ocr-pages phase blend clean -y

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
