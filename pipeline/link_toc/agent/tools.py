from typing import List, Dict, Optional, Any
import re

from infra.pipeline.storage.book_storage import BookStorage


def list_boundaries(
    storage: BookStorage,
    start_page: Optional[int] = None,
    end_page: Optional[int] = None
) -> List[Dict]:
    """
    List boundary pages from label-structure with heading previews.

    Returns ALL boundaries by default (only 50-200 items, easy to scan).
    Optional range filtering for targeted searches.

    Filters out TOC pages - they are not chapter boundaries.

    Args:
        storage: BookStorage instance
        start_page: Optional start of page range
        end_page: Optional end of page range

    Returns:
        List of {scan_page, heading_preview, boundary_confidence}
        Sorted by scan_page ascending
    """
    from pipeline.label_structure.merge import get_merged_page

    # Get TOC page range to exclude from boundaries
    toc_pages = set()
    find_toc_stage = storage.stage("find-toc")
    finder_result_path = find_toc_stage.output_dir / "finder_result.json"
    if finder_result_path.exists():
        finder_data = find_toc_stage.load_file("finder_result.json")
        if finder_data and finder_data.get("toc_found"):
            page_range = finder_data.get("toc_page_range", {})
            toc_start = page_range.get("start_page", 0)
            toc_end = page_range.get("end_page", 0)
            if toc_start > 0 and toc_end >= toc_start:
                toc_pages = set(range(toc_start, toc_end + 1))

    # Get total pages from metadata
    metadata = storage.load_metadata()
    total_pages = metadata.get('total_pages', 0)

    boundaries = []

    for page_num in range(1, total_pages + 1):
        # Skip TOC pages
        if page_num in toc_pages:
            continue

        # Apply range filter if provided
        if start_page and page_num < start_page:
            continue
        if end_page and page_num > end_page:
            continue

        try:
            # Get merged page data (includes gap healing fixes)
            page_data = get_merged_page(storage, page_num)

            # Skip pages without headings
            if not page_data.headings_present or not page_data.headings:
                continue

            # Filter for chapter-level headings (level 1-2)
            chapter_headings = [h for h in page_data.headings if h.level <= 2]

            if not chapter_headings:
                continue

            # Use first heading as preview
            heading_preview = chapter_headings[0].text

            # Calculate confidence based on heading level and chapter marker
            # Level 1 = high confidence boundary, Level 2 = medium confidence
            if chapter_headings[0].level == 1:
                confidence = 0.9
            else:
                confidence = 0.7

            # Boost confidence if gap healing confirmed this as a chapter marker
            if page_data.chapter_marker:
                confidence = min(1.0, confidence + 0.1)

            boundaries.append({
                "scan_page": page_num,
                "heading_preview": heading_preview,
                "boundary_confidence": confidence,
            })

        except FileNotFoundError:
            # label-structure data doesn't exist for this page yet
            continue
        except Exception:
            # Other errors - skip page
            continue

    # Sort by page number
    boundaries.sort(key=lambda x: x["scan_page"])

    return boundaries


def grep_text(
    query: str,
    storage: BookStorage
) -> List[Dict]:
    """
    Search entire book's OCR for text pattern (creates "heatmap").

    Key insight: Running headers create DENSITY. Dense regions show chapter extent,
    first page in dense region is the boundary.

    Example:
        grep_text("Chapter XIII")
        → Page 44: 1 match (previous chapter mentions next)
        → Page 45: 4 matches (BOUNDARY + running headers start)
        → Pages 46-62: 3-4 matches each (running headers continue)
        → Page 63: 1 match (next chapter starts)

        Agent sees: Dense region 45-62, boundary at page 45!

    Filters out TOC pages - chapter titles in the TOC are not the actual chapters.

    Args:
        query: Text to search for (supports regex)
        storage: BookStorage instance

    Returns:
        List of {scan_page, match_count, context_snippets[]}
        Sorted by scan_page ascending
        Only includes pages with matches
    """
    from rapidfuzz import fuzz

    # Get TOC page range to exclude from search results
    toc_pages = set()
    find_toc_stage = storage.stage("find-toc")
    finder_result_path = find_toc_stage.output_dir / "finder_result.json"
    if finder_result_path.exists():
        finder_data = find_toc_stage.load_file("finder_result.json")
        if finder_data and finder_data.get("toc_found"):
            page_range = finder_data.get("toc_page_range", {})
            toc_start = page_range.get("start_page", 0)
            toc_end = page_range.get("end_page", 0)
            if toc_start > 0 and toc_end >= toc_start:
                toc_pages = set(range(toc_start, toc_end + 1))

    metadata = storage.load_metadata()
    total_pages = metadata.get('total_pages', 0)

    results = []

    for page_num in range(1, total_pages + 1):
        # Skip TOC pages
        if page_num in toc_pages:
            continue
        try:
            ocr_text = get_page_ocr(page_num, storage)

            # Try both exact and fuzzy matching
            exact_matches = []
            fuzzy_matches = []

            # Exact regex search
            try:
                pattern = re.compile(query, re.IGNORECASE)
                exact_matches = list(pattern.finditer(ocr_text))
            except re.error:
                # If regex fails, treat as literal string
                pattern = re.compile(re.escape(query), re.IGNORECASE)
                exact_matches = list(pattern.finditer(ocr_text))

            # Collect context snippets
            snippets = []
            for match in exact_matches[:3]:  # Max 3 snippets per page
                start = max(0, match.start() - 50)
                end = min(len(ocr_text), match.end() + 50)
                snippet = ocr_text[start:end].strip()
                snippet = ' '.join(snippet.split())  # Normalize whitespace
                if snippet not in snippets:
                    snippets.append(snippet)

            if exact_matches:
                results.append({
                    "scan_page": page_num,
                    "match_count": len(exact_matches),
                    "context_snippets": snippets,
                })

        except FileNotFoundError:
            continue
        except Exception:
            continue

    # Sort by page number
    results.sort(key=lambda x: x["scan_page"])

    return results


def get_page_ocr(
    page_num: int,
    storage: BookStorage
) -> str:
    """
    Get full OCR text for a specific page.

    Args:
        page_num: Scan page number
        storage: BookStorage instance

    Returns:
        Full OCR text from olm-ocr stage
    """
    from pipeline.olm_ocr.schemas import OlmOcrPageOutput

    ocr_pages_stage = storage.stage("olm-ocr")

    try:
        ocr_data = ocr_pages_stage.load_page(page_num, schema=OlmOcrPageOutput)
        return ocr_data.get('text', '')
    except FileNotFoundError:
        return ""
