"""Book loading utilities for MCP server."""

import json
import os
from pathlib import Path
from typing import Optional

from pipeline.common_structure.schemas.common_structure_output import CommonStructureOutput


def get_storage_root() -> Path:
    """Get the book storage root directory."""
    root = os.getenv("BOOK_STORAGE_ROOT", "~/Documents/shelf")
    return Path(root).expanduser().resolve()


def list_completed_books() -> list[dict]:
    """List all books with completed common-structure stage.

    Returns:
        List of dicts with scan_id and basic metadata.
    """
    root = get_storage_root()
    if not root.exists():
        return []

    books = []
    for book_dir in root.iterdir():
        if not book_dir.is_dir():
            continue

        structure_file = book_dir / "common-structure" / "merge" / "structure.json"
        if structure_file.exists():
            try:
                with open(structure_file) as f:
                    data = json.load(f)

                metadata = data.get("metadata", {})
                books.append({
                    "scan_id": book_dir.name,
                    "title": metadata.get("title", book_dir.name),
                    "author": metadata.get("author"),
                    "total_chapters": data.get("total_chapters", 0),
                    "total_parts": data.get("total_parts", 0),
                    "total_entries": data.get("total_entries", 0),
                })
            except (json.JSONDecodeError, KeyError):
                continue

    return sorted(books, key=lambda b: b["scan_id"])


def load_book_structure(scan_id: str) -> Optional[CommonStructureOutput]:
    """Load the complete structure for a book.

    Args:
        scan_id: The book identifier.

    Returns:
        CommonStructureOutput if found, None otherwise.
    """
    root = get_storage_root()
    structure_file = root / scan_id / "common-structure" / "merge" / "structure.json"

    if not structure_file.exists():
        return None

    with open(structure_file) as f:
        data = json.load(f)

    return CommonStructureOutput.model_validate(data)


def load_book_structure_raw(scan_id: str) -> Optional[dict]:
    """Load the raw structure JSON for a book (without validation).

    Args:
        scan_id: The book identifier.

    Returns:
        Raw dict if found, None otherwise.
    """
    root = get_storage_root()
    structure_file = root / scan_id / "common-structure" / "merge" / "structure.json"

    if not structure_file.exists():
        return None

    with open(structure_file) as f:
        return json.load(f)
