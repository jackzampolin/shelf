from typing import List, Optional, Tuple
from dataclasses import dataclass

from infra import PipelineLogger, BookStorage


@dataclass
class ChapterBoundary:
    entry_id: str
    title: str
    level: int
    entry_number: Optional[str]
    scan_page_start: int
    scan_page_end: int
    toc_confidence: float
    link_source: str
    semantic_type: str


def detect_semantic_type(title: str, level: int, entry_number: Optional[str]) -> str:
    title_lower = title.lower()

    if any(x in title_lower for x in ["preface", "foreword", "introduction", "prologue"]):
        return title_lower.split()[0]

    if any(x in title_lower for x in ["epilogue", "afterword", "appendix", "index"]):
        return title_lower.split()[0]

    if level == 1:
        return "part"
    elif level == 2:
        return "chapter"
    else:
        return "section"


def load_linked_toc(storage: BookStorage, logger: PipelineLogger) -> List[dict]:
    link_toc_storage = storage.stage("link-toc")
    linked_toc_path = link_toc_storage.output_dir / "linked_toc.json"

    if not linked_toc_path.exists():
        raise FileNotFoundError(
            f"Linked ToC not found at {linked_toc_path}. Run link-toc stage first."
        )

    import json
    with open(linked_toc_path, "r") as f:
        linked_toc = json.load(f)

    return linked_toc.get("entries", [])


def detect_boundaries(
    storage: BookStorage,
    logger: PipelineLogger,
    total_pages: int
) -> List[ChapterBoundary]:
    toc_entries = load_linked_toc(storage, logger)

    if not toc_entries:
        logger.warning("No ToC entries found - cannot detect boundaries")
        return []

    linked_entries = [
        entry for entry in toc_entries
        if entry.get("scan_page") is not None
    ]

    if not linked_entries:
        logger.error("No entries were successfully linked to scan pages")
        return []

    linked_entries.sort(key=lambda e: e["scan_page"])

    boundaries: List[ChapterBoundary] = []

    for i, entry in enumerate(linked_entries):
        start_page = entry["scan_page"]

        if i < len(linked_entries) - 1:
            end_page = linked_entries[i + 1]["scan_page"] - 1
        else:
            end_page = total_pages

        level = entry.get("level", 2)
        entry_num = entry.get("entry_number")
        if level == 1:
            entry_id = f"part_{i+1:03d}"
        elif level == 2:
            entry_id = f"ch_{i+1:03d}"
        else:
            entry_id = f"sec_{i+1:03d}"

        semantic_type = detect_semantic_type(entry["title"], level, entry_num)

        boundary = ChapterBoundary(
            entry_id=entry_id,
            title=entry["title"],
            level=level,
            entry_number=entry_num,
            scan_page_start=start_page,
            scan_page_end=end_page,
            toc_confidence=1.0,  # Link-toc no longer provides confidence (see agent logs for details)
            link_source="toc",
            semantic_type=semantic_type
        )

        boundaries.append(boundary)
        logger.debug(f"Boundary detected: {boundary.entry_id} '{boundary.title}' pages {start_page}-{end_page}")

    return boundaries


def classify_front_back_matter(
    boundaries: List[ChapterBoundary],
    total_pages: int
) -> Tuple[List[int], List[int]]:
    front_matter_pages = []
    back_matter_pages = []

    if boundaries:
        first_chapter_start = boundaries[0].scan_page_start
        if first_chapter_start > 1:
            front_matter_pages = list(range(1, first_chapter_start))

    back_matter_types = {"epilogue", "afterword", "appendix", "index"}
    for boundary in boundaries:
        if boundary.semantic_type in back_matter_types:
            back_matter_pages.extend(
                range(boundary.scan_page_start, boundary.scan_page_end + 1)
            )

    return front_matter_pages, back_matter_pages
