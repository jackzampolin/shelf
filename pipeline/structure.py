#!/usr/bin/env python3
"""
Book Structure Analysis - Main Entry Point

Thin wrapper that delegates to the modular structure package.

Usage:
    python pipeline/structure.py <scan-id>

Example:
    python pipeline/structure.py modest-lovelace
"""

import sys
from pathlib import Path

# Import from modular structure package
from pipeline.structure import BookStructurer


def main():
    if len(sys.argv) < 2:
        print("Usage: python pipeline/structure.py <scan-id>")
        print("Example: python pipeline/structure.py modest-lovelace")
        sys.exit(1)

    book_slug = sys.argv[1]

    structurer = BookStructurer(book_slug)
    structurer.process_book()


if __name__ == "__main__":
    main()
