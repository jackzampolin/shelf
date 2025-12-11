from typing import List, Dict, Optional
import re

from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger


# Back matter section keywords for detection
BACK_MATTER_KEYWORDS = [
    "acknowledgment", "acknowledgement", "footnote", "endnote", "note",
    "appendix", "appendices", "glossary", "index", "bibliography",
    "reference", "source", "credit", "about the author"
]

FRONT_MATTER_KEYWORDS = [
    "title", "copyright", "dedication", "preface", "foreword",
    "introduction", "prologue", "contents", "map", "illustration"
]


def get_book_structure(
    storage: BookStorage,
    logger: Optional[PipelineLogger] = None
) -> Dict:
    """
    Analyze book structure to identify front matter, body, and back matter boundaries.
    Uses ToC entries to detect section types.
    """
    total_pages = storage.load_metadata().get('total_pages', 0)

    # Load ToC
    try:
        toc_data = storage.stage("extract-toc").load_file("toc.json")
        entries = toc_data.get("entries", [])
    except FileNotFoundError:
        return {
            "total_pages": total_pages,
            "front_matter": {"end_page": None, "sections": []},
            "body": {"start_page": 1, "end_page": total_pages, "first_chapter": None, "last_chapter": None},
            "back_matter": {"start_page": None, "sections": []}
        }

    if not entries:
        return {
            "total_pages": total_pages,
            "front_matter": {"end_page": None, "sections": []},
            "body": {"start_page": 1, "end_page": total_pages, "first_chapter": None, "last_chapter": None},
            "back_matter": {"start_page": None, "sections": []}
        }

    # Classify each entry
    front_sections = []
    body_chapters = []
    back_sections = []

    # Track if we've hit back matter - once we do, everything after is back matter
    in_back_matter = False

    for entry in entries:
        title = entry.get("title", "").lower()
        entry_number = entry.get("entry_number")

        # Check if it's back matter by keyword
        is_back_keyword = any(kw in title for kw in BACK_MATTER_KEYWORDS)
        # Check if it's front matter (no number, front matter keyword)
        is_front = entry_number is None and any(kw in title for kw in FRONT_MATTER_KEYWORDS)

        # Once we hit back matter, stay in back matter mode
        if is_back_keyword:
            in_back_matter = True

        if in_back_matter:
            back_sections.append(entry)
        elif is_front:
            front_sections.append(entry)
        else:
            body_chapters.append(entry)

    # Determine boundaries
    # Front matter ends where body begins
    front_end = None
    body_start = None
    body_end = None
    back_start = None

    if body_chapters:
        # First body chapter determines where front matter ends
        first_body = body_chapters[0]
        last_body = body_chapters[-1]
        body_start = 1  # Will be refined when linked
        body_end = total_pages  # Will be refined when we find back matter

    if back_sections:
        # Back matter starts at first back matter entry
        # Use printed page number if available, otherwise estimate
        first_back = back_sections[0]
        printed_page = first_back.get("printed_page_number")
        if printed_page:
            # Estimate scan page from printed page (typical offset 15-30 for front matter)
            try:
                printed_num = int(printed_page)
                # Use a conservative offset - actual offset varies but 20-30 is typical
                back_start = printed_num + 25
            except (ValueError, TypeError):
                back_start = total_pages - (len(back_sections) * 20)
        else:
            back_start = total_pages - (len(back_sections) * 20)  # Rough estimate

    # Get ToC page range for front matter estimate
    toc_range = toc_data.get("toc_page_range", {})
    toc_end = toc_range.get("end_page", 0)
    if toc_end:
        front_end = toc_end

    return {
        "total_pages": total_pages,
        "front_matter": {
            "end_page": front_end,
            "sections": [_classify_section(e.get("title", "")) for e in front_sections]
        },
        "body": {
            "start_page": body_start,
            "end_page": body_end,
            "first_chapter": body_chapters[0].get("title") if body_chapters else None,
            "last_chapter": body_chapters[-1].get("title") if body_chapters else None
        },
        "back_matter": {
            "start_page": back_start,
            "sections": [_classify_section(e.get("title", "")) for e in back_sections]
        }
    }


def _classify_section(title: str) -> str:
    """Classify a section title into a standard type."""
    title_lower = title.lower()

    for kw in BACK_MATTER_KEYWORDS + FRONT_MATTER_KEYWORDS:
        if kw in title_lower:
            return kw.replace(" ", "_")

    return title_lower[:30]


def is_in_back_matter(page_num: int, book_structure: Dict) -> bool:
    """Check if a page number is in back matter based on book structure."""
    back_start = book_structure.get("back_matter", {}).get("start_page")
    if back_start and page_num >= back_start:
        return True
    return False


def get_heading_pages(
    storage: BookStorage,
    start_page: Optional[int] = None,
    end_page: Optional[int] = None,
    logger: Optional[PipelineLogger] = None
) -> List[Dict]:
    from pipeline.label_structure.merge import get_merged_page

    toc_pages = _get_toc_page_range(storage)
    total_pages = storage.load_metadata().get('total_pages', 0)
    heading_pages = []

    for page_num in range(1, total_pages + 1):
        if page_num in toc_pages:
            continue
        if start_page and page_num < start_page:
            continue
        if end_page and page_num > end_page:
            continue

        try:
            page_data = get_merged_page(storage, page_num)

            if not page_data.headings_present or not page_data.headings:
                continue

            chapter_headings = [h for h in page_data.headings if h.level <= 2]
            if not chapter_headings:
                continue

            first_heading = chapter_headings[0]

            page_number_data = None
            if page_data.page_number.present and page_data.page_number.number:
                page_number_data = {
                    "number": page_data.page_number.number,
                    "confidence": page_data.page_number.confidence,
                }

            heading_pages.append({
                "scan_page": page_num,
                "heading": {"text": first_heading.text, "level": first_heading.level},
                "page_number": page_number_data,
                "confidence": 0.9 if first_heading.level == 1 else 0.7,
            })

        except FileNotFoundError:
            continue
        except (AttributeError, KeyError) as e:
            if logger:
                logger.warning(f"Malformed label-structure data for page {page_num}: {e}")
            continue
        except Exception as e:
            if logger:
                logger.error(f"Error in get_heading_pages for page {page_num}: {e}", exc_info=True)
            raise

    heading_pages.sort(key=lambda x: x["scan_page"])
    return heading_pages


def _get_toc_page_range(storage: BookStorage) -> set:
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
    return toc_pages


def grep_text(
    query: str,
    storage: BookStorage,
    logger: Optional[PipelineLogger] = None
) -> List[Dict]:
    toc_pages = _get_toc_page_range(storage)
    total_pages = storage.load_metadata().get('total_pages', 0)
    results = []

    for page_num in range(1, total_pages + 1):
        if page_num in toc_pages:
            continue

        try:
            ocr_text = get_page_ocr(page_num, storage, logger)

            try:
                pattern = re.compile(query, re.IGNORECASE)
                matches = list(pattern.finditer(ocr_text))
            except re.error:
                pattern = re.compile(re.escape(query), re.IGNORECASE)
                matches = list(pattern.finditer(ocr_text))

            if not matches:
                continue

            snippets = []
            for match in matches[:3]:
                start = max(0, match.start() - 50)
                end = min(len(ocr_text), match.end() + 50)
                snippet = ' '.join(ocr_text[start:end].split())
                if snippet not in snippets:
                    snippets.append(snippet)

            results.append({
                "scan_page": page_num,
                "match_count": len(matches),
                "context_snippets": snippets,
            })

        except FileNotFoundError:
            continue
        except (AttributeError, TypeError) as e:
            if logger:
                logger.warning(f"Malformed OCR data for page {page_num}: {e}")
            continue
        except Exception as e:
            if logger:
                logger.error(f"Error in grep_text for page {page_num}: {e}", exc_info=True)
            raise

    results.sort(key=lambda x: x["scan_page"])
    return results


def get_page_ocr(
    page_num: int,
    storage: BookStorage,
    logger: Optional[PipelineLogger] = None
) -> str:
    try:
        blend_data = storage.stage("ocr-pages").load_page(page_num, subdir="blend")
        return blend_data.get("markdown", "")
    except FileNotFoundError:
        return ""
