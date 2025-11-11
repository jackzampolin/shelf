import re
import json
from pathlib import Path
from typing import Dict, List, Tuple
from collections import defaultdict

from infra.pipeline.storage.book_storage import BookStorage


SEARCH_PATTERNS = [
    r"\bTable of Contents\b",
    r"\bTABLE OF CONTENTS\b",
    r"\bContents\b",  # Match "Contents" word boundary (handles "Contents —" etc)
    r"\bCONTENTS\b",
    r"\bPreface\b",
    r"\bPREFACE\b",
    r"\bAuthor's Note\b",
    r"\bForeword\b",
    r"\bIntroduction\b",
    r"\bINTRODUCTION\b",
    r"\bPrologue\b",
    r"\bAcknowledgments\b",
    r"\bAcknowledgements\b",
    r"\bACKNOWLEDGMENTS\b",
    r"\bDedication\b",
    r"\bDedicated to\b",
    r"\bAbout the Author\b",
    r"\bAbout The Author\b",
    r"\bChapter\s+\d+",
    r"\bCHAPTER\s+\d+",
    r"^Chapter\s+[IVX]+",
    r"\bPart\s+\d+",
    r"\bPART\s+\d+",
    r"^Part\s+[IVX]+",
    r"\bSection\s+\d+",
    r"\bAppendix\b",
    r"\bAPPENDIX\b",
    r"\bBibliography\b",
    r"\bWorks Cited\b",
    r"\bReferences\b",
    r"\bIndex\b",
    r"\bINDEX\b",
    r"\bEpilogue\b",
    r"\bAfterword\b",
    r"\bEndnotes\b",
    r"\bNotes\b",
]


def extract_text_from_page(storage: BookStorage, page_num: int) -> str:
    """Extract OCR text from olm-ocr stage."""
    from pipeline.olm_ocr.schemas import OlmOcrPageOutput

    ocr_stage_storage = storage.stage('olm-ocr')
    page_data = ocr_stage_storage.load_page(page_num, schema=OlmOcrPageOutput)
    if not page_data:
        raise FileNotFoundError(f"OCR data for page {page_num} not found")
    return page_data.get("text", "")


def extract_context(text: str, match: str, match_pos: int, context_chars: int = 100) -> str:
    start = max(0, match_pos - context_chars)
    end = min(len(text), match_pos + len(match) + context_chars)

    context = text[start:end]
    context = ' '.join(context.split())

    if len(context) > 200:
        context = context[:200] + "..."

    return context


def search_patterns_with_context(text: str, patterns: List[str]) -> List[Dict[str, str]]:
    matches = []
    seen = set()

    for pattern in patterns:
        for match in re.finditer(pattern, text, re.MULTILINE | re.IGNORECASE):
            keyword = match.group(0)
            context = extract_context(text, keyword, match.start())

            key = (keyword, context)
            if key not in seen:
                seen.add(key)
                matches.append({
                    "keyword": keyword,
                    "context": context
                })

    return matches


def generate_grep_report(storage: BookStorage, max_pages: int = 50) -> Dict:
    metadata = storage.load_metadata()
    total_pages = metadata.get("total_pages", 0)

    search_end = min(max_pages, total_pages)
    pages_with_matches = []

    for page_num in range(1, search_end + 1):
        try:
            text = extract_text_from_page(storage, page_num)
            matches = search_patterns_with_context(text, SEARCH_PATTERNS)

            if matches:
                pages_with_matches.append({
                    "page": page_num,
                    "matches": matches
                })

        except FileNotFoundError:
            continue
        except Exception as e:
            print(f"Warning: Error processing page {page_num}: {e}")
            continue

    report = {
        "pages": pages_with_matches,
        "search_range": f"1-{search_end}",
        "total_pages_searched": search_end,
    }

    return report


def summarize_grep_report(report: Dict) -> str:
    lines = []
    lines.append(f"Searched pages: {report['search_range']}")
    lines.append("")

    pages = report.get("pages", [])
    if pages:
        lines.append(f"Found matches on {len(pages)} pages:")
        for page_data in pages[:10]:
            page_num = page_data["page"]
            match_count = len(page_data["matches"])
            keywords = [m["keyword"] for m in page_data["matches"]]
            lines.append(f"  Page {page_num}: {match_count} matches → {', '.join(keywords[:5])}")
            if len(keywords) > 5:
                lines.append(f"             (+{len(keywords) - 5} more)")

        if len(pages) > 10:
            lines.append(f"  ... and {len(pages) - 10} more pages")
    else:
        lines.append("No matches found")

    return "\n".join(lines)
