"""Coverage calculation and gap detection utilities."""

from typing import List, Tuple, Optional
from ..schemas import EnrichedToCEntry, PageGap, PatternAnalysis


def compute_page_ranges(entries: List[EnrichedToCEntry]) -> List[Tuple[int, int]]:
    """
    Compute page ranges for each entry.

    Each entry covers from its scan_page to the next entry's scan_page - 1.
    The last entry covers to the end of the body range.
    """
    if not entries:
        return []

    # Sort by scan_page
    sorted_entries = sorted(entries, key=lambda e: e.scan_page)
    ranges = []

    for i, entry in enumerate(sorted_entries):
        start = entry.scan_page
        if i + 1 < len(sorted_entries):
            end = sorted_entries[i + 1].scan_page - 1
        else:
            # Last entry - will be extended to body_end by caller
            end = start
        ranges.append((start, end))

    return ranges


def find_gaps(
    entries: List[EnrichedToCEntry],
    body_range: Tuple[int, int],
    min_gap_size: int = 1
) -> List[PageGap]:
    """
    Find all page gaps in the enriched ToC.

    A gap is any range of pages not covered by an entry.
    """
    if not entries:
        return [PageGap(
            start_page=body_range[0],
            end_page=body_range[1],
            size=body_range[1] - body_range[0] + 1,
            entry_before=None,
            entry_before_page=None,
            entry_after=None,
            entry_after_page=None,
        )]

    body_start, body_end = body_range
    sorted_entries = sorted(entries, key=lambda e: e.scan_page)
    gaps = []

    # Check gap before first entry
    first_entry = sorted_entries[0]
    if first_entry.scan_page > body_start:
        gap_size = first_entry.scan_page - body_start
        if gap_size >= min_gap_size:
            gaps.append(PageGap(
                start_page=body_start,
                end_page=first_entry.scan_page - 1,
                size=gap_size,
                entry_before=None,
                entry_before_page=None,
                entry_after=first_entry.title,
                entry_after_page=first_entry.scan_page,
            ))

    # Check gaps between entries
    for i in range(len(sorted_entries) - 1):
        current = sorted_entries[i]
        next_entry = sorted_entries[i + 1]

        # Gap is between current entry's page and next entry's page
        # An entry "owns" from its scan_page to next entry's scan_page - 1
        # So gap is only if there's more than 1 page difference that seems wrong
        gap_start = current.scan_page + 1
        gap_end = next_entry.scan_page - 1

        if gap_end >= gap_start:
            gap_size = gap_end - gap_start + 1
            if gap_size >= min_gap_size:
                gaps.append(PageGap(
                    start_page=gap_start,
                    end_page=gap_end,
                    size=gap_size,
                    entry_before=current.title,
                    entry_before_page=current.scan_page,
                    entry_after=next_entry.title,
                    entry_after_page=next_entry.scan_page,
                ))

    # Check gap after last entry (this is usually the last entry's content, not a gap)
    # We don't flag this as a gap since the last entry extends to body_end

    return gaps


def compute_coverage_stats(
    entries: List[EnrichedToCEntry],
    body_range: Tuple[int, int]
) -> Tuple[int, float]:
    """
    Compute coverage statistics.

    Returns:
        Tuple of (pages_covered, coverage_percent)
    """
    body_start, body_end = body_range
    total_pages = body_end - body_start + 1

    if not entries:
        return 0, 0.0

    sorted_entries = sorted(entries, key=lambda e: e.scan_page)

    # Each entry covers from its page to the next entry - 1 (or body_end for last)
    covered = 0
    for i, entry in enumerate(sorted_entries):
        start = max(entry.scan_page, body_start)
        if i + 1 < len(sorted_entries):
            end = min(sorted_entries[i + 1].scan_page - 1, body_end)
        else:
            end = body_end

        if end >= start:
            covered += end - start + 1

    coverage_percent = (covered / total_pages * 100) if total_pages > 0 else 0.0
    return covered, coverage_percent


def get_toc_entries_in_range(
    toc_entries: List,
    start_page: int,
    end_page: int
) -> List:
    """Get original ToC entries that fall within a page range."""
    return [
        e for e in toc_entries
        if e.scan_page and start_page <= e.scan_page <= end_page
    ]


def is_back_matter_gap(
    gap: PageGap,
    pattern_analysis: Optional[PatternAnalysis]
) -> bool:
    """Check if a gap is in excluded back matter (bibliography, index, etc.)."""
    if not pattern_analysis:
        return False

    for excluded in pattern_analysis.excluded_page_ranges:
        if (gap.start_page >= excluded.start_page and
            gap.end_page <= excluded.end_page):
            return True

    return False
