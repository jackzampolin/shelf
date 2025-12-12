"""URI-based resource handlers for MCP server."""

import json
from typing import Optional

from shelf_mcp.utils.loader import load_book_structure_raw


def get_book_metadata(scan_id: str) -> str:
    """Get book metadata as a resource.

    URI: book://{scan_id}/metadata
    """
    data = load_book_structure_raw(scan_id)

    if data is None:
        return json.dumps({"error": f"Book '{scan_id}' not found."})

    metadata = data.get("metadata", {})
    return json.dumps(metadata, indent=2)


def get_book_toc(scan_id: str) -> str:
    """Get book table of contents as a resource.

    URI: book://{scan_id}/toc
    """
    data = load_book_structure_raw(scan_id)

    if data is None:
        return json.dumps({"error": f"Book '{scan_id}' not found."})

    entries = data.get("entries", [])
    toc = []

    for entry in entries:
        toc.append({
            "entry_id": entry.get("entry_id"),
            "title": entry.get("title"),
            "level": entry.get("level"),
            "parent_id": entry.get("parent_id"),
        })

    return json.dumps(toc, indent=2)


def get_chapter_content(scan_id: str, entry_id: str) -> str:
    """Get chapter content as a resource.

    URI: book://{scan_id}/chapter/{entry_id}
    """
    data = load_book_structure_raw(scan_id)

    if data is None:
        return json.dumps({"error": f"Book '{scan_id}' not found."})

    entries = data.get("entries", [])
    entry = None

    for e in entries:
        if e.get("entry_id") == entry_id:
            entry = e
            break

    if entry is None:
        return json.dumps({"error": f"Entry '{entry_id}' not found."})

    content = entry.get("content")
    if content is None:
        return json.dumps({"error": "No content available for this entry."})

    return content.get("final_text", "")
