"""
Phase 1a: Parse Table of Contents from merged pages.

This phase runs BEFORE structure analysis to extract the book's declared structure.
The ToC provides top-down structure information that complements the ground-up
signals from report.csv (chapter headings, page regions, etc.).

Cost: ~$0.05-0.10 per book (single LLM call on ToC text)
Time: ~5-15 seconds
"""

import csv
import json
from pathlib import Path
from typing import Tuple, Optional

from infra.llm.client import LLMClient
from infra.pipeline.logger import PipelineLogger
from infra.storage.book_storage import BookStorage

from .schemas import TableOfContents, PageRange
from .prompts_v2 import TOC_PARSING_PROMPT


def find_toc_pages(labels_report_path: Path) -> Optional[PageRange]:
    """
    Find ToC pages from labels report.

    Args:
        labels_report_path: Path to labels/report.csv

    Returns:
        PageRange for ToC pages, or None if not found
    """
    with open(labels_report_path, "r") as f:
        rows = list(csv.DictReader(f))

    # Look for toc_area page_region
    toc_pages = []
    for row in rows:
        if row.get("page_region") == "toc_area":
            toc_pages.append(int(row["page_num"]))

    if not toc_pages:
        return None

    # Return continuous range
    return PageRange(start_page=min(toc_pages), end_page=max(toc_pages))


def extract_toc_text(storage: BookStorage, toc_range: PageRange) -> str:
    """
    Extract text from ToC pages.

    Args:
        storage: BookStorage instance
        toc_range: Page range for ToC

    Returns:
        Combined text from all ToC pages
    """
    merged_storage = storage.stage("merged")

    toc_text_parts = []
    for page_num in range(toc_range.start_page, toc_range.end_page + 1):
        page_data = merged_storage.load_page(page_num)

        # Extract text from merged page blocks
        page_text_lines = []
        blocks = page_data.get("blocks", [])
        for block in blocks:
            paragraphs = block.get("paragraphs", [])
            for para in paragraphs:
                text = para.get("text", "")
                if text:
                    page_text_lines.append(text)

        if page_text_lines:
            toc_text_parts.append(f"=== Page {page_num} ===\n" + "\n".join(page_text_lines) + "\n")

    return "\n".join(toc_text_parts)


def parse_toc(
    storage: BookStorage,
    labels_report_path: Path,
    model: str,
    logger: PipelineLogger,
) -> Tuple[Optional[TableOfContents], float]:
    """
    Parse Table of Contents from merged pages.

    Phase 1a of build-structure: Extract ToC to inform structure analysis.

    Args:
        storage: BookStorage instance
        labels_report_path: Path to labels/report.csv
        model: LLM model to use
        logger: Pipeline logger

    Returns:
        Tuple of (TableOfContents or None, cost_usd)
        Returns (None, 0.0) if no ToC found

    Raises:
        ValueError: If LLM response doesn't match schema
    """
    logger.info("Phase 1a: Parsing Table of Contents")

    # Find ToC pages
    toc_range = find_toc_pages(labels_report_path)

    if not toc_range:
        logger.info("No ToC pages found (page_region=toc_area not detected)")
        return None, 0.0

    logger.info("Found ToC pages", start=toc_range.start_page, end=toc_range.end_page)

    # Extract text from ToC pages
    toc_text = extract_toc_text(storage, toc_range)

    if not toc_text.strip():
        logger.warning("ToC pages found but no text extracted")
        return None, 0.0

    logger.info("Extracted ToC text", chars=len(toc_text))

    # Prepare LLM call with structured output
    response_schema = TableOfContents.model_json_schema()

    messages = [
        {"role": "system", "content": TOC_PARSING_PROMPT},
        {"role": "user", "content": f"Table of Contents Text:\n\n{toc_text}"},
    ]

    # Make LLM call
    client = LLMClient()
    logger.info("Calling LLM for ToC parsing", model=model)
    print(f"\n📖 Parsing Table of Contents ({toc_range.end_page - toc_range.start_page + 1} pages)...")

    response_text, usage, cost_usd = client.call(
        model=model,
        messages=messages,
        response_format=response_schema,
        max_tokens=4000,
        stream=True,
    )

    logger.info(
        "LLM response received",
        tokens_in=usage.get("prompt_tokens", 0),
        tokens_out=usage.get("completion_tokens", 0),
        cost=f"${cost_usd:.4f}",
    )

    # Parse response into TableOfContents
    response_text = response_text.strip()
    if response_text.startswith("```json"):
        response_text = response_text[7:]
    if response_text.startswith("```"):
        response_text = response_text[3:]
    if response_text.endswith("```"):
        response_text = response_text[:-3]
    response_text = response_text.strip()

    try:
        response_data = json.loads(response_text)
        toc = TableOfContents(**response_data)
    except json.JSONDecodeError as e:
        logger.error("Invalid JSON from LLM", error=str(e), response_preview=response_text[:1000])
        raise ValueError(f"LLM response is not valid JSON: {e}")
    except Exception as e:
        logger.error("Failed to validate schema", error=str(e))
        raise ValueError(f"LLM response doesn't match TableOfContents schema: {e}")

    logger.info(
        "ToC parsed successfully",
        entries=len(toc.entries),
        chapters=toc.total_chapters,
        sections=toc.total_sections,
        confidence=f"{toc.parsing_confidence:.2f}",
    )

    return toc, cost_usd
