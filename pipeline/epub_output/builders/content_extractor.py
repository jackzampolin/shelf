from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from pathlib import Path

from infra.pipeline.storage.book_storage import BookStorage


@dataclass
class Footnote:
    number: str
    text: str
    source_page: int


@dataclass
class ChapterContent:
    entry_id: str
    title: str
    level: int
    page_start: int
    page_end: int
    body_text: str
    footnotes: List[Footnote]
    images: List[Dict[str, Any]]


def extract_chapter_content(
    storage: BookStorage,
    entry_id: str,
    title: str,
    level: int,
    page_start: int,
    page_end: int,
    ocr_source: str,
    include_headers_footers: bool = False
) -> ChapterContent:
    ocr_storage = storage.stage(ocr_source)
    label_storage = storage.stage("label-structure")

    body_paragraphs = []
    footnotes = []
    images = []

    for page_num in range(page_start, page_end + 1):
        ocr_data = ocr_storage.load_page(page_num)
        if not ocr_data:
            continue

        label_data = label_storage.load_page(page_num)
        if not label_data:
            body_paragraphs.append(ocr_data.get("text", ""))
            continue

        blocks = label_data.get("blocks", [])

        for block in blocks:
            block_type = block.get("type", "unknown")
            text = block.get("text", "").strip()

            if not text:
                continue

            if block_type == "BODY":
                body_paragraphs.append(text)

            elif block_type == "FOOTNOTE":
                footnote_num = block.get("footnote_number", "?")
                footnotes.append(Footnote(
                    number=footnote_num,
                    text=text,
                    source_page=page_num
                ))

            elif block_type in ["HEADER", "FOOTER"] and include_headers_footers:
                body_paragraphs.append(text)

            elif block_type in ["CHAPTER_HEADING", "SECTION_HEADING"]:
                pass

        page_images = ocr_data.get("images", [])
        for img in page_images:
            images.append({
                "page": page_num,
                "path": img.get("path"),
                "caption": img.get("caption", "")
            })

    body_text = "\n\n".join(p for p in body_paragraphs if p)

    return ChapterContent(
        entry_id=entry_id,
        title=title,
        level=level,
        page_start=page_start,
        page_end=page_end,
        body_text=body_text,
        footnotes=footnotes,
        images=images
    )
