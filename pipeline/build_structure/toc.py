"""
Table of Contents extraction from merged pages.

Extracts the book's declared structure from ToC pages, providing top-down
structure information that complements the ground-up signals from labels stage.

Cost: ~$0.05-0.10 per book (single LLM call on ToC text)
Time: ~5-15 seconds
"""

import csv
import json
from pathlib import Path
from typing import Tuple, Optional

from infra.llm.batch_client import LLMBatchClient
from infra.llm.models import LLMRequest
from infra.pipeline.logger import PipelineLogger
from infra.storage.book_storage import BookStorage

from .schemas import TableOfContents, PageRange
from .toc_prompts import TOC_PARSING_PROMPT


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
    print(f"\n📖 Phase 1a: Parsing Table of Contents...")

    # Find ToC pages using agentic search
    from infra.agents.toc_finder import find_toc_pages_agentic

    toc_range, search_cost = find_toc_pages_agentic(
        storage=storage,
        logger=logger,
        max_iterations=15,
        verbose=True
    )

    if not toc_range:
        logger.info("No ToC pages found by agent")
        print("   ⊘ No ToC found (agent exhausted search)")
        return None, search_cost

    logger.info("Found ToC pages", start=toc_range.start_page, end=toc_range.end_page)

    # Extract text from ToC pages
    toc_text = extract_toc_text(storage, toc_range)

    if not toc_text.strip():
        logger.warning("ToC pages found but no text extracted")
        print("   ⊘ ToC pages found but no text extracted (skipping)")
        return None, 0.0

    logger.info("Extracted ToC text", chars=len(toc_text))

    messages = [
        {"role": "system", "content": TOC_PARSING_PROMPT},
        {"role": "user", "content": f"Table of Contents Text:\n\n{toc_text}"},
    ]

    # Build JSON schema for structured output
    # Note: OpenRouter doesn't support "strict": True
    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "table_of_contents",
            "schema": TableOfContents.model_json_schema()
        }
    }

    # Create LLM request
    toc_pages = toc_range.end_page - toc_range.start_page + 1
    request = LLMRequest(
        id="parse_toc",
        model=model,
        messages=messages,
        temperature=0.0,
        max_tokens=4000,
        response_format=response_format
    )

    # Make LLM call with batch client (single request)
    log_dir = storage.stage("build_structure").output_dir / "logs"
    batch_client = LLMBatchClient(
        max_workers=1,
        max_retries=5,  # Retry on validation failures
        verbose=False,  # Disable verbose for single call (we'll show our own progress)
        log_dir=log_dir
    )

    logger.info("Calling LLM for ToC parsing", model=model, toc_pages=toc_pages)
    print(f"   ⏳ Parsing ToC with LLM...")

    results = batch_client.process_batch([request])

    # Show completion with cost
    batch_stats = batch_client.get_batch_stats(total_requests=1)
    print(f"   ✓ ToC parsed (cost: ${batch_stats.total_cost_usd:.4f})")

    # Extract result
    result = results[0]
    if not result.success:
        raise ValueError(f"LLM call failed: {result.error_message}")

    # Parse response as TableOfContents
    toc = TableOfContents(**result.parsed_json)
    parsing_cost = result.cost_usd
    total_cost = search_cost + parsing_cost

    logger.info(
        "ToC parsed successfully",
        entries=len(toc.entries),
        chapters=toc.total_chapters,
        sections=toc.total_sections,
        confidence=f"{toc.parsing_confidence:.2f}",
        search_cost=f"${search_cost:.4f}",
        parsing_cost=f"${parsing_cost:.4f}",
        total_cost=f"${total_cost:.4f}",
    )

    print(f"   ✓ Parsed {len(toc.entries)} ToC entries ({toc.total_chapters} chapters, {toc.total_sections} sections)")
    print(f"   💰 Total cost: ${total_cost:.4f} (search: ${search_cost:.4f}, parsing: ${parsing_cost:.4f})")

    return toc, total_cost
