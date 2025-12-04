from typing import List, Dict, Optional
import re

from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger


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
