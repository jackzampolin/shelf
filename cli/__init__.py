import argparse
import cli.library
import cli.book
import cli.config
from cli.batch import setup_batch_parser
from cli.batch_parallel import setup_batch_parallel_parser
from cli.serve import setup_serve_parser


def create_parser():
    parser = argparse.ArgumentParser(
        prog='shelf',
        description='Shelf - Turn physical books into digital libraries',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Configuration (run first!)
  shelf init                              # Initialize library config
  shelf init --migrate                    # Migrate from .env file
  shelf config show                       # Show current config
  shelf config set defaults.max_workers 20
  shelf config provider list              # List OCR providers
  shelf config provider add qwen --type deepinfra --model Qwen/Qwen2-VL

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

    cli.config.setup_parser(subparsers)
    cli.library.setup_parser(subparsers)
    cli.book.setup_parser(subparsers)
    setup_batch_parser(subparsers)
    setup_batch_parallel_parser(subparsers)
    setup_serve_parser(subparsers)

    return parser


def main():
    parser = create_parser()
    args = parser.parse_args()
    args.func(args)
