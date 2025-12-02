from typing import List, Dict, Optional, Any
import re

from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger


def get_heading_pages(
    storage: BookStorage,
    start_page: Optional[int] = None,
    end_page: Optional[int] = None,
    logger: Optional[PipelineLogger] = None
) -> List[Dict]:
    """
    Get pages with chapter-level headings from label-structure.

    Returns ALL pages with headings by default (typically 50-200 pages).
    Optional range filtering for targeted searches.

    Filters out TOC pages - they are not chapter pages.

    Args:
        storage: BookStorage instance
        start_page: Optional start of page range
        end_page: Optional end of page range

    Returns:
        List of {scan_page, heading: {text, level}, page_number: {number, confidence}, confidence}
        Sorted by scan_page ascending
    """
    from pipeline.label_structure.merge import get_merged_page

    # Get TOC page range to exclude from results
    toc_pages = set()
    extract_toc_stage = storage.stage("extract-toc")
    finder_result_path = extract_toc_stage.output_dir / "finder_result.json"
    if finder_result_path.exists():
        finder_data = extract_toc_stage.load_file("finder_result.json")
        if finder_data and finder_data.get("toc_found"):
            page_range = finder_data.get("toc_page_range", {})
            toc_start = page_range.get("start_page", 0)
            toc_end = page_range.get("end_page", 0)
            if toc_start > 0 and toc_end >= toc_start:
                toc_pages = set(range(toc_start, toc_end + 1))

    # Get total pages from metadata
    metadata = storage.load_metadata()
    total_pages = metadata.get('total_pages', 0)

    heading_pages = []

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

            # Use first heading
            first_heading = chapter_headings[0]

            # Calculate confidence based on heading level
            # Level 1 = high confidence, Level 2 = medium confidence
            if first_heading.level == 1:
                confidence = 0.9
            else:
                confidence = 0.7

            # Build heading data
            heading_data = {
                "text": first_heading.text,
                "level": first_heading.level,
            }

            # Build page_number data (optional)
            page_number_data = None
            if page_data.page_number.present and page_data.page_number.number:
                page_number_data = {
                    "number": page_data.page_number.number,
                    "confidence": page_data.page_number.confidence,
                }

            heading_pages.append({
                "scan_page": page_num,
                "heading": heading_data,
                "page_number": page_number_data,
                "confidence": confidence,
            })

        except FileNotFoundError:
            # label-structure data doesn't exist for this page yet - expected
            continue
        except (AttributeError, KeyError) as e:
            # Data structure issue - log for debugging but continue
            if logger:
                logger.warning(
                    f"Malformed label-structure data for page {page_num}: {e}"
                )
            continue
        except Exception as e:
            # Unexpected error - log with high severity and fail fast
            if logger:
                logger.error(
                    f"Unexpected error processing page {page_num} in get_heading_pages: {e}",
                    exc_info=True
                )
            raise

    # Sort by page number
    heading_pages.sort(key=lambda x: x["scan_page"])

    return heading_pages


def grep_text(
    query: str,
    storage: BookStorage,
    logger: Optional[PipelineLogger] = None
) -> List[Dict]:
    """
    Search entire book's OCR for text pattern (creates "heatmap").

    Key insight: Running headers create DENSITY. Dense regions show chapter extent,
    first page in dense region is where the chapter starts.

    Example:
        grep_text("Chapter XIII")
        → Page 44: 1 match (previous chapter mentions next)
        → Page 45: 4 matches (CHAPTER START + running headers begin)
        → Pages 46-62: 3-4 matches each (running headers continue)
        → Page 63: 1 match (next chapter starts)

        Agent sees: Dense region 45-62, chapter starts at page 45!

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
    extract_toc_stage = storage.stage("extract-toc")
    finder_result_path = extract_toc_stage.output_dir / "finder_result.json"
    if finder_result_path.exists():
        finder_data = extract_toc_stage.load_file("finder_result.json")
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
            ocr_text = get_page_ocr(page_num, storage, logger)

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
            # OCR data doesn't exist for this page - expected
            continue
        except (AttributeError, TypeError) as e:
            # Data structure issue (e.g., ocr_text is not a string) - log but continue
            if logger:
                logger.warning(
                    f"Malformed OCR data for page {page_num} in grep_text: {e}"
                )
            continue
        except Exception as e:
            # Unexpected error - log with high severity and fail fast
            if logger:
                logger.error(
                    f"Unexpected error processing page {page_num} in grep_text: {e}",
                    exc_info=True
                )
            raise

    # Sort by page number
    results.sort(key=lambda x: x["scan_page"])

    return results


def get_page_ocr(
    page_num: int,
    storage: BookStorage,
    logger: Optional[PipelineLogger] = None
) -> str:
    """
    Get full OCR text for a specific page.

    Uses the blended OCR output which synthesizes high-quality markdown
    from multiple providers.

    Args:
        page_num: Scan page number
        storage: BookStorage instance
        logger: Optional logger for warnings

    Returns:
        Full OCR text from blend, or empty string if not found
    """
    ocr_stage = storage.stage("ocr-pages")

    try:
        blend_data = ocr_stage.load_page(page_num, subdir="blend")
        return blend_data.get("markdown", "")
    except FileNotFoundError:
        if logger:
            logger.warning(
                f"Blend OCR data missing for page {page_num} - returning empty text"
            )
        return ""
