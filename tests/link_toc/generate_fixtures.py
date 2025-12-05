#!/usr/bin/env python3
"""
Generate expected result fixtures for link-toc accuracy tests.

Reads actual link-toc outputs from the library and creates fixture files.
Run this after manually verifying link-toc outputs are correct.

Usage:
    # Generate fixture for a specific book
    python tests/link_toc/generate_fixtures.py --book accidental-president

    # Generate fixtures for all books with link-toc outputs
    python tests/link_toc/generate_fixtures.py --all

    # Dry run (show what would be generated)
    python tests/link_toc/generate_fixtures.py --book accidental-president --dry-run
"""

import sys
from pathlib import Path

# Add project root to path for imports
_project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_project_root))

import argparse
import json
from typing import Dict, Any, Optional, List

from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.storage.library import Library


FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "expected" / "link_toc"


def strip_linked_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Strip verbose fields from linked entry, keeping comparison-relevant fields."""
    return {
        "entry_number": entry.get("entry_number"),
        "title": entry.get("title", ""),
        "level": entry.get("level", 1),
        "level_name": entry.get("level_name"),
        "printed_page_number": entry.get("printed_page_number"),
        "scan_page": entry.get("scan_page"),
    }


def strip_enriched_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Strip verbose fields from enriched entry, keeping comparison-relevant fields."""
    return {
        "title": entry.get("title", ""),
        "scan_page": entry.get("scan_page"),
        "level": entry.get("level", 1),
        "source": entry.get("source", "toc"),
        "entry_number": entry.get("entry_number"),
        "printed_page_number": entry.get("printed_page_number"),
    }


def generate_fixture(book_id: str) -> Optional[Dict[str, Any]]:
    """
    Generate fixture data from a book's link-toc output.

    Args:
        book_id: Book scan ID

    Returns:
        Fixture data dict, or None if link-toc not complete
    """
    storage = BookStorage(book_id)
    stage_storage = storage.stage("link-toc")

    # Check for required outputs
    linked_toc_path = stage_storage.output_dir / "linked_toc.json"
    enriched_toc_path = stage_storage.output_dir / "enriched_toc.json"

    if not linked_toc_path.exists():
        print(f"  Skipping {book_id}: linked_toc.json not found")
        return None

    if not enriched_toc_path.exists():
        print(f"  Skipping {book_id}: enriched_toc.json not found")
        return None

    # Load outputs
    linked_toc = stage_storage.load_file("linked_toc.json")
    enriched_toc = stage_storage.load_file("enriched_toc.json")

    if not linked_toc or not enriched_toc:
        print(f"  Skipping {book_id}: failed to load outputs")
        return None

    # Strip verbose fields
    linked_entries = [strip_linked_entry(e) for e in linked_toc.get("entries", []) if e is not None]
    enriched_entries = [strip_enriched_entry(e) for e in enriched_toc.get("entries", [])]

    # Count linked vs unlinked
    linked_count = sum(1 for e in linked_entries if e.get("scan_page") is not None)
    unlinked_count = len(linked_entries) - linked_count

    # Count by source in enriched
    toc_count = sum(1 for e in enriched_entries if e.get("source") == "toc")
    discovered_count = sum(1 for e in enriched_entries if e.get("source") == "discovered")
    missing_found_count = sum(1 for e in enriched_entries if e.get("source") == "missing_found")

    fixture = {
        "scan_id": book_id,
        "linked_toc": {
            "entries": linked_entries,
            "total_entries": len(linked_entries),
            "linked_entries": linked_count,
            "unlinked_entries": unlinked_count,
        },
        "enriched_toc": {
            "entries": enriched_entries,
            "original_toc_count": toc_count,
            "discovered_count": discovered_count + missing_found_count,
            "total_entries": len(enriched_entries),
        },
    }

    return fixture


def save_fixture(book_id: str, fixture: Dict[str, Any], dry_run: bool = False):
    """Save fixture to file."""
    fixture_path = FIXTURE_DIR / f"{book_id}.json"

    if dry_run:
        print(f"  [DRY RUN] Would write: {fixture_path}")
        print(f"    linked_toc: {fixture['linked_toc']['total_entries']} entries "
              f"({fixture['linked_toc']['linked_entries']} linked)")
        print(f"    enriched_toc: {fixture['enriched_toc']['total_entries']} entries "
              f"({fixture['enriched_toc']['discovered_count']} discovered)")
        return

    # Ensure directory exists
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    with open(fixture_path, 'w') as f:
        json.dump(fixture, f, indent=2)

    print(f"  Wrote: {fixture_path}")
    print(f"    linked_toc: {fixture['linked_toc']['total_entries']} entries "
          f"({fixture['linked_toc']['linked_entries']} linked)")
    print(f"    enriched_toc: {fixture['enriched_toc']['total_entries']} entries "
          f"({fixture['enriched_toc']['discovered_count']} discovered)")


def list_books_with_link_toc() -> List[str]:
    """List all books that have link-toc outputs."""
    library = Library()
    books_with_output = []

    for book_info in library.list_books():
        # Library.list_books() returns dicts with 'scan_id' key
        book_id = book_info["scan_id"]
        storage = BookStorage(book_id)
        stage_storage = storage.stage("link-toc")

        linked_toc_path = stage_storage.output_dir / "linked_toc.json"
        enriched_toc_path = stage_storage.output_dir / "enriched_toc.json"

        if linked_toc_path.exists() and enriched_toc_path.exists():
            books_with_output.append(book_id)

    return books_with_output


def main():
    parser = argparse.ArgumentParser(
        description="Generate expected result fixtures for link-toc accuracy tests",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        "--book",
        help="Generate fixture for a specific book"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Generate fixtures for all books with link-toc outputs"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be generated without writing files"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List books with link-toc outputs"
    )

    args = parser.parse_args()

    if args.list:
        books = list_books_with_link_toc()
        print(f"Books with link-toc outputs ({len(books)}):")
        for book_id in books:
            print(f"  {book_id}")
        return

    if not args.book and not args.all:
        parser.print_help()
        print("\nError: Must specify --book or --all")
        sys.exit(1)

    if args.book:
        book_ids = [args.book]
    else:
        book_ids = list_books_with_link_toc()

    print(f"Generating fixtures for {len(book_ids)} book(s)...")
    print()

    generated = 0
    skipped = 0

    for book_id in book_ids:
        print(f"Processing: {book_id}")
        fixture = generate_fixture(book_id)

        if fixture:
            save_fixture(book_id, fixture, dry_run=args.dry_run)
            generated += 1
        else:
            skipped += 1

        print()

    print(f"Done. Generated: {generated}, Skipped: {skipped}")


if __name__ == "__main__":
    main()
