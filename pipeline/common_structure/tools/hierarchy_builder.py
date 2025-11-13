from typing import List

from infra import PipelineLogger

from ..schemas import StructureEntry
from .boundary_detector import ChapterBoundary


def build_structure_entries(
    boundaries: List[ChapterBoundary],
    logger: PipelineLogger
) -> List[StructureEntry]:
    entries: List[StructureEntry] = []

    for boundary in boundaries:
        entry = StructureEntry(
            entry_id=boundary.entry_id,
            title=boundary.title,
            level=boundary.level,
            entry_number=boundary.entry_number,
            scan_page_start=boundary.scan_page_start,
            scan_page_end=boundary.scan_page_end,
            parent_id=None,
            confidence=boundary.toc_confidence,
            source=boundary.link_source,
            semantic_type=boundary.semantic_type
        )
        entries.append(entry)

    build_hierarchy(entries, logger)
    return entries


def build_hierarchy(entries: List[StructureEntry], logger: PipelineLogger) -> None:
    recent_by_level: dict[int, StructureEntry] = {}

    for entry in entries:
        current_level = entry.level

        if current_level > 1:
            parent_level = current_level - 1
            if parent_level in recent_by_level:
                parent = recent_by_level[parent_level]
                entry.parent_id = parent.entry_id
                logger.debug(f"Set parent: {entry.entry_id} → {parent.entry_id}")

        recent_by_level[current_level] = entry

        levels_to_clear = [lvl for lvl in recent_by_level if lvl > current_level]
        for lvl in levels_to_clear:
            del recent_by_level[lvl]


def calculate_hierarchy_stats(entries: List[StructureEntry]) -> dict[str, int]:
    return {
        "total_entries": len(entries),
        "total_parts": sum(1 for e in entries if e.level == 1),
        "total_chapters": sum(1 for e in entries if e.level == 2),
        "total_sections": sum(1 for e in entries if e.level == 3),
    }
