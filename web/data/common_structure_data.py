"""Data loaders for common-structure stage web view."""

from typing import Optional, Dict, Any, List
from infra.pipeline.storage.book_storage import BookStorage


def get_common_structure_data(storage: BookStorage) -> Optional[Dict[str, Any]]:
    """Load the complete structure.json output."""
    stage_storage = storage.stage("common-structure")
    structure_path = stage_storage.output_dir / "structure.json"

    if not structure_path.exists():
        return None

    return stage_storage.load_file("structure.json")


def get_structure_summary(storage: BookStorage) -> Optional[Dict[str, Any]]:
    """Get a summary of the structure for the overview."""
    data = get_common_structure_data(storage)
    if not data:
        return None

    entries = data.get("entries", [])

    return {
        "metadata": data.get("metadata", {}),
        "total_entries": data.get("total_entries", len(entries)),
        "total_chapters": data.get("total_chapters", 0),
        "total_parts": data.get("total_parts", 0),
        "total_sections": data.get("total_sections", 0),
        "total_pages": len(data.get("page_references", [])),
        "front_matter_pages": len(data.get("front_matter_pages", [])),
        "back_matter_pages": len(data.get("back_matter_pages", [])),
        "extracted_at": data.get("extracted_at", ""),
        "cost_usd": data.get("cost_usd", 0),
        "processing_time_seconds": data.get("processing_time_seconds", 0),
    }


def get_structure_entries(storage: BookStorage) -> List[Dict[str, Any]]:
    """Get all structure entries with content info."""
    data = get_common_structure_data(storage)
    if not data:
        return []

    entries = []
    for entry in data.get("entries", []):
        content = entry.get("content", {})

        entry_summary = {
            "entry_id": entry.get("entry_id"),
            "title": entry.get("title"),
            "level": entry.get("level"),
            "entry_number": entry.get("entry_number"),
            "scan_page_start": entry.get("scan_page_start"),
            "scan_page_end": entry.get("scan_page_end"),
            "semantic_type": entry.get("semantic_type"),
            "word_count": content.get("word_count", 0) if content else 0,
            "page_count": entry.get("scan_page_end", 0) - entry.get("scan_page_start", 0) + 1,
            "edits_count": len(content.get("edits_applied", [])) if content else 0,
            "has_content": bool(content and content.get("final_text")),
        }
        entries.append(entry_summary)

    return entries


def get_entry_detail(storage: BookStorage, entry_id: str) -> Optional[Dict[str, Any]]:
    """Get full details for a single entry including text content."""
    data = get_common_structure_data(storage)
    if not data:
        return None

    for entry in data.get("entries", []):
        if entry.get("entry_id") == entry_id:
            return entry

    return None


def get_page_references(storage: BookStorage) -> List[Dict[str, Any]]:
    """Get page reference mappings (scan -> printed)."""
    data = get_common_structure_data(storage)
    if not data:
        return []

    return data.get("page_references", [])
