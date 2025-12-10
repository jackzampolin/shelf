"""
Text extraction and cleaning for common-structure stage.

Flow:
1. Load OCR markdown + label-structure classifications per page
2. Mechanically strip running headers and page numbers
3. Join pages with continuation detection
4. (Later) LLM polish via edit list
"""

import re
from typing import List, Optional, Tuple
from dataclasses import dataclass

from infra import BookStorage, PipelineLogger
from ..schemas import PageText, SectionText


@dataclass
class PageData:
    """Raw data loaded for a single page."""
    scan_page: int
    markdown: str
    printed_page: Optional[str]
    running_header: Optional[str]
    has_page_number_in_header: bool


def load_page_data(
    storage: BookStorage,
    scan_page: int
) -> Optional[PageData]:
    """Load OCR text and labels for a single page."""
    # Load OCR markdown
    ocr_storage = storage.stage("ocr-pages")
    ocr_data = ocr_storage.load_file(f"blend/page_{scan_page:04d}.json")

    if not ocr_data:
        return None

    markdown = ocr_data.get("markdown", "")

    # Load label-structure unified classification
    label_storage = storage.stage("label-structure")
    unified_data = label_storage.load_file(f"unified/page_{scan_page:04d}.json")

    printed_page = None
    running_header = None
    has_page_number_in_header = False

    if unified_data:
        page_num_info = unified_data.get("page_number", {})
        if page_num_info.get("present"):
            printed_page = page_num_info.get("number")
            has_page_number_in_header = page_num_info.get("location") == "header"

        header_info = unified_data.get("running_header", {})
        if header_info.get("present"):
            running_header = header_info.get("text")

    return PageData(
        scan_page=scan_page,
        markdown=markdown,
        printed_page=printed_page,
        running_header=running_header,
        has_page_number_in_header=has_page_number_in_header
    )


def clean_page_text(page_data: PageData) -> str:
    """
    Mechanically clean a page's text by removing running header and page number.

    Common patterns:
    - "**6 / The Accidental President**" (page number / running header)
    - "6 / The Accidental President" (without bold)
    - "The Accidental President / 6"
    - Just page number alone on a line
    """
    text = page_data.markdown
    lines = text.split('\n')

    if not lines:
        return text

    # Check first few lines for header pattern
    cleaned_lines = []
    header_removed = False

    for i, line in enumerate(lines):
        # Only check first 3 lines for headers
        if i < 3 and not header_removed:
            if _is_header_line(line, page_data):
                header_removed = True
                continue

        cleaned_lines.append(line)

    # Strip leading/trailing whitespace but preserve internal structure
    result = '\n'.join(cleaned_lines).strip()

    return result


def _is_header_line(line: str, page_data: PageData) -> bool:
    """Detect if a line is a running header/page number to remove."""
    stripped = line.strip()

    if not stripped:
        return False

    # Remove markdown bold markers for comparison
    plain = stripped.replace('**', '').replace('*', '')

    # Pattern: "6 / Title" or "Title / 6"
    if '/' in plain:
        parts = [p.strip() for p in plain.split('/')]
        if len(parts) == 2:
            # Check if one part is the page number
            if page_data.printed_page:
                if parts[0] == page_data.printed_page or parts[1] == page_data.printed_page:
                    return True

            # Check if one part matches running header
            if page_data.running_header:
                header_lower = page_data.running_header.lower()
                if parts[0].lower() == header_lower or parts[1].lower() == header_lower:
                    return True

    # Pattern: Just the running header alone
    if page_data.running_header:
        if plain.lower() == page_data.running_header.lower():
            return True

    # Pattern: Just the page number alone
    if page_data.printed_page and page_data.has_page_number_in_header:
        if plain == page_data.printed_page:
            return True

    return False


def extract_section_text(
    storage: BookStorage,
    logger: PipelineLogger,
    scan_page_start: int,
    scan_page_end: int
) -> SectionText:
    """
    Extract and clean text for a section (range of pages).

    Steps:
    1. Load and clean each page
    2. Join pages with continuation detection
    3. Return SectionText with page_texts and mechanical_text
    """
    page_texts: List[PageText] = []

    for scan_page in range(scan_page_start, scan_page_end + 1):
        page_data = load_page_data(storage, scan_page)

        if not page_data:
            logger.warning(f"No OCR data for page {scan_page}")
            continue

        cleaned = clean_page_text(page_data)

        page_texts.append(PageText(
            scan_page=scan_page,
            printed_page=page_data.printed_page,
            raw_text=page_data.markdown,
            cleaned_text=cleaned
        ))

    # Join pages
    mechanical_text, page_breaks = join_pages(page_texts)

    # Calculate word count
    word_count = len(mechanical_text.split())

    return SectionText(
        page_texts=page_texts,
        mechanical_text=mechanical_text,
        edits_applied=[],
        final_text=mechanical_text,  # Will be updated by LLM polish
        word_count=word_count,
        page_breaks=page_breaks
    )


def join_pages(page_texts: List[PageText]) -> Tuple[str, List[int]]:
    """
    Join cleaned page texts, handling continuations across page breaks.

    Returns: (joined_text, page_break_positions)

    Continuation detection:
    - Line ends with hyphen: join without space (de-hyphenate)
    - Line ends mid-sentence (no terminal punctuation): join with space
    - Line ends with sentence: join with double newline
    """
    if not page_texts:
        return "", []

    page_breaks: List[int] = []
    parts: List[str] = []

    for i, page_text in enumerate(page_texts):
        text = page_text.cleaned_text

        if i == 0:
            parts.append(text)
            continue

        # Record page break
        page_breaks.append(page_text.scan_page)

        prev_text = parts[-1] if parts else ""

        # Determine how to join
        join_str = _determine_join(prev_text, text)

        if join_str == "":
            # Continuation (hyphenation) - modify previous part
            if parts and parts[-1].endswith('-'):
                parts[-1] = parts[-1][:-1]  # Remove hyphen

        parts.append(join_str + text)

    joined = ''.join(parts)

    return joined, page_breaks


def _determine_join(prev_text: str, next_text: str) -> str:
    """Determine the join string between two page texts."""
    if not prev_text:
        return ""

    prev_stripped = prev_text.rstrip()

    # Hyphenation: word split across pages
    if prev_stripped.endswith('-'):
        # Check if it's a real hyphenation (lowercase letter before hyphen)
        if len(prev_stripped) >= 2 and prev_stripped[-2].islower():
            return ""  # Join without space, hyphen will be removed

    # Check for sentence ending
    sentence_enders = '.!?"\''
    if prev_stripped and prev_stripped[-1] in sentence_enders:
        return "\n\n"  # Paragraph break

    # Mid-sentence continuation
    return " "
