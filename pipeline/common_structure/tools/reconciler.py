from typing import List
from difflib import SequenceMatcher

from infra import PipelineLogger

from .boundary_detector import ChapterBoundary
from .heading_detector import HeadingObservation


def text_similarity(text1: str, text2: str) -> float:
    if not text1 or not text2:
        return 0.0
    return SequenceMatcher(None, text1.lower().strip(), text2.lower().strip()).ratio()


def reconcile_toc_with_headings(
    toc_boundaries: List[ChapterBoundary],
    headings: List[HeadingObservation],
    logger: PipelineLogger
) -> List[ChapterBoundary]:
    reconciled = []

    for boundary in toc_boundaries:
        headings_in_range = [
            h for h in headings
            if boundary.scan_page_start <= h.scan_page <= boundary.scan_page_end
        ]

        if not headings_in_range:
            logger.debug(f"{boundary.entry_id}: No headings found in range, keeping ToC boundary")
            reconciled.append(boundary)
            continue

        best_match = None
        best_similarity = 0.0

        for heading in headings_in_range:
            similarity = text_similarity(boundary.title, heading.text)
            if similarity > best_similarity:
                best_similarity = similarity
                best_match = heading

        if best_match and best_similarity > 0.6:
            logger.debug(
                f"{boundary.entry_id}: Reconciled with heading on page {best_match.scan_page} "
                f"(similarity: {best_similarity:.2f})"
            )
            boundary.scan_page_start = best_match.scan_page
            boundary.link_source = "reconciled"
            boundary.toc_confidence = min(boundary.toc_confidence,
                                         1.0 if best_match.confidence == "high" else 0.8)
        else:
            logger.debug(f"{boundary.entry_id}: No good heading match, keeping ToC boundary")

        reconciled.append(boundary)

    return reconciled
