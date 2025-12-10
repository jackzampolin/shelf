"""Data loaders for common-structure stage web view."""

import json
from typing import Optional, Dict, Any, List
from pathlib import Path
from infra.pipeline.storage.book_storage import BookStorage


def get_common_structure_data(storage: BookStorage) -> Optional[Dict[str, Any]]:
    """Load the complete structure.json output."""
    stage_storage = storage.stage("common-structure")

    # Try new multi-phase location first
    structure_path = stage_storage.output_dir / "merge" / "structure.json"
    if structure_path.exists():
        return stage_storage.load_file("merge/structure.json")

    # Fall back to old location (for backwards compatibility)
    structure_path = stage_storage.output_dir / "structure.json"
    if structure_path.exists():
        return stage_storage.load_file("structure.json")

    return None


def get_skeleton_data(storage: BookStorage) -> Optional[Dict[str, Any]]:
    """Load the skeleton from build_structure phase (during processing)."""
    stage_storage = storage.stage("common-structure")
    skeleton_path = stage_storage.output_dir / "build_structure" / "structure_skeleton.json"

    if skeleton_path.exists():
        return stage_storage.load_file("build_structure/structure_skeleton.json")

    return None


def get_polished_entry(storage: BookStorage, entry_id: str) -> Optional[Dict[str, Any]]:
    """Load a single polished entry file from polish_entries phase."""
    stage_storage = storage.stage("common-structure")
    entry_path = stage_storage.output_dir / "polish_entries" / f"{entry_id}.json"

    if entry_path.exists():
        with open(entry_path) as f:
            return json.load(f)

    return None


def count_polished_entries(storage: BookStorage) -> int:
    """Count how many entries have been polished (for progress display)."""
    stage_storage = storage.stage("common-structure")
    polish_dir = stage_storage.output_dir / "polish_entries"

    if not polish_dir.exists():
        return 0

    return len(list(polish_dir.glob("*.json")))


def get_structure_summary(storage: BookStorage) -> Optional[Dict[str, Any]]:
    """Get a summary of the structure for the overview."""
    # Try final merged data first
    data = get_common_structure_data(storage)

    if data:
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
            "is_complete": True,
            "polished_count": len(entries),
        }

    # Fall back to skeleton data (during processing)
    skeleton = get_skeleton_data(storage)
    if skeleton:
        entries = skeleton.get("entries", [])
        stats = skeleton.get("stats", {})
        polished_count = count_polished_entries(storage)

        return {
            "metadata": {},
            "total_entries": stats.get("total_entries", len(entries)),
            "total_chapters": stats.get("total_chapters", 0),
            "total_parts": stats.get("total_parts", 0),
            "total_sections": stats.get("total_sections", 0),
            "total_pages": skeleton.get("total_pages", 0),
            "front_matter_pages": 0,
            "back_matter_pages": 0,
            "extracted_at": "",
            "cost_usd": 0,
            "processing_time_seconds": 0,
            "is_complete": False,
            "polished_count": polished_count,
        }

    return None


def get_structure_entries(storage: BookStorage) -> List[Dict[str, Any]]:
    """Get all structure entries with content info."""
    # Try final merged data first
    data = get_common_structure_data(storage)

    if data:
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
                "is_polished": True,
            }
            entries.append(entry_summary)
        return entries

    # Fall back to skeleton + polished entries (during processing)
    skeleton = get_skeleton_data(storage)
    if skeleton:
        entries = []
        for entry in skeleton.get("entries", []):
            # Check if this entry has been polished
            polished = get_polished_entry(storage, entry.get("entry_id"))
            content = polished.get("content") if polished else None

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
                "is_polished": polished is not None,
            }
            entries.append(entry_summary)
        return entries

    return []


def get_entry_detail(storage: BookStorage, entry_id: str) -> Optional[Dict[str, Any]]:
    """Get full details for a single entry including text content."""
    # Try final merged data first
    data = get_common_structure_data(storage)
    if data:
        for entry in data.get("entries", []):
            if entry.get("entry_id") == entry_id:
                return entry
        return None

    # Fall back to skeleton + polished entry (during processing)
    skeleton = get_skeleton_data(storage)
    if skeleton:
        for entry in skeleton.get("entries", []):
            if entry.get("entry_id") == entry_id:
                # Merge with polished content if available
                polished = get_polished_entry(storage, entry_id)
                if polished and polished.get("content"):
                    entry["content"] = polished["content"]
                return entry

    return None


def get_page_references(storage: BookStorage) -> List[Dict[str, Any]]:
    """Get page reference mappings (scan -> printed)."""
    data = get_common_structure_data(storage)
    if not data:
        return []

    return data.get("page_references", [])
