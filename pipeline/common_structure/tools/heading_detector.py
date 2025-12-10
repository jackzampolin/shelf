from typing import List, Optional
from dataclasses import dataclass

from infra import BookStorage, PipelineLogger


@dataclass
class HeadingObservation:
    scan_page: int
    level: int
    text: str
    confidence: str


def extract_headings_from_labels(
    storage: BookStorage,
    logger: PipelineLogger,
    total_pages: int
) -> List[HeadingObservation]:
    label_structure_storage = storage.stage("label-structure")
    headings = []

    for page_num in range(1, total_pages + 1):
        # Load from mechanical subdirectory where headings are stored
        page_data = label_structure_storage.load_file(f"mechanical/page_{page_num:04d}.json")
        if not page_data:
            continue

        # Mechanical format has headings_present and headings list directly
        if not page_data.get("headings_present", False):
            continue

        heading_items = page_data.get("headings", [])

        for heading_item in heading_items:
            headings.append(HeadingObservation(
                scan_page=page_num,
                level=heading_item.get("level", 2),
                text=heading_item.get("text", ""),
                confidence="high"  # mechanical extraction
            ))

    logger.debug(f"Extracted {len(headings)} headings from label-structure")
    return headings
