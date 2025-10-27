"""
Table of Contents extraction from merged pages.

Extracts the book's declared structure from ToC pages, providing top-down
structure information that complements the ground-up signals from labels stage.

Cost: ~$0.05-0.10 per book (initial parse + refinement)
Time: ~10-30 seconds
"""

import csv
import json
from pathlib import Path
from typing import Tuple, Optional
from PIL import Image

from infra.llm.batch_client import LLMBatchClient
from infra.llm.models import LLMRequest
from infra.pipeline.logger import PipelineLogger
from infra.storage.book_storage import BookStorage
from infra.utils.pdf import downsample_for_vision

from .schemas import TableOfContents, PageRange
from .toc_prompts import TOC_PARSING_PROMPT, TOC_REFINEMENT_PROMPT


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


def load_toc_images(storage: BookStorage, toc_range: PageRange) -> list:
    """
    Load ToC page images for vision-based parsing.

    Args:
        storage: BookStorage instance
        toc_range: Page range for ToC

    Returns:
        List of downsampled PIL Images
    """
    source_storage = storage.stage("source")
    toc_images = []

    for page_num in range(toc_range.start_page, toc_range.end_page + 1):
        page_file = source_storage.output_dir / f"page_{page_num:04d}.png"
        if page_file.exists():
            image = Image.open(page_file)
            image = downsample_for_vision(image)
            toc_images.append(image)

    return toc_images


def refine_toc_parse(
    initial_toc: TableOfContents,
    toc_images: list,
    model: str,
    logger: PipelineLogger,
    log_dir: Path,
) -> Tuple[TableOfContents, float]:
    """
    Refine ToC parse with vision-based second pass.

    Args:
        initial_toc: Initial parse result from text-based parsing
        toc_images: List of ToC page images
        model: LLM model to use
        logger: Pipeline logger
        log_dir: Directory for logging

    Returns:
        Tuple of (refined TableOfContents, refinement cost)
    """
    logger.info("Refining ToC parse with vision verification", entries=len(initial_toc.entries))
    print(f"   🔍 Refining parse with vision verification...")

    # Build refinement user prompt
    initial_json = initial_toc.model_dump_json(indent=2)
    user_prompt = f"""Here is the initial ToC parse from text-only analysis:

```json
{initial_json}
```

Please review the ToC page images and verify/correct this parse, focusing on:
1. Hierarchy levels (visual indentation)
2. Page numbers (check right-aligned column)
3. Chapter numbers (extract from titles)

Return the corrected JSON following the same schema."""

    # Build JSON schema for structured output
    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "table_of_contents_refined",
            "schema": TableOfContents.model_json_schema()
        }
    }

    # Create refinement LLM request with images
    request = LLMRequest(
        id="refine_toc",
        model=model,
        messages=[
            {"role": "system", "content": TOC_REFINEMENT_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        images=toc_images,  # Vision input
        temperature=0.0,
        max_tokens=4000,
        response_format=response_format
    )

    # Make LLM call
    batch_client = LLMBatchClient(
        max_workers=1,
        max_retries=5,
        verbose=False,
        log_dir=log_dir
    )

    results = batch_client.process_batch([request])

    # Extract result
    result = results[0]
    if not result.success:
        logger.warning("Refinement failed, using initial parse", error=result.error_message)
        print(f"   ⚠️  Refinement failed, using initial parse")
        return initial_toc, 0.0

    # Parse response as TableOfContents
    refined_toc = TableOfContents(**result.parsed_json)
    refinement_cost = result.cost_usd

    # Compare changes
    hierarchy_changes = sum(1 for i, entry in enumerate(refined_toc.entries)
                           if i < len(initial_toc.entries) and entry.level != initial_toc.entries[i].level)
    page_num_changes = sum(1 for i, entry in enumerate(refined_toc.entries)
                          if i < len(initial_toc.entries) and entry.printed_page_number != initial_toc.entries[i].printed_page_number)

    logger.info(
        "ToC refinement complete",
        hierarchy_changes=hierarchy_changes,
        page_num_changes=page_num_changes,
        cost=f"${refinement_cost:.4f}"
    )
    print(f"   ✓ Refinement complete (hierarchy: {hierarchy_changes} changes, page nums: {page_num_changes} changes)")

    return refined_toc, refinement_cost


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

    # Extract result
    result = results[0]
    if not result.success:
        raise ValueError(f"LLM call failed: {result.error_message}")

    # Parse response as TableOfContents (initial parse)
    initial_toc = TableOfContents(**result.parsed_json)
    parsing_cost = result.cost_usd

    print(f"   ✓ Initial parse: {len(initial_toc.entries)} entries ({initial_toc.total_chapters} chapters, {initial_toc.total_sections} sections)")

    # Load ToC images for refinement
    toc_images = load_toc_images(storage, toc_range)

    # Refine parse with vision verification
    toc, refinement_cost = refine_toc_parse(
        initial_toc=initial_toc,
        toc_images=toc_images,
        model=model,
        logger=logger,
        log_dir=log_dir
    )

    total_cost = search_cost + parsing_cost + refinement_cost

    print(f"   ✓ Final: {len(toc.entries)} entries ({toc.total_chapters} chapters, {toc.total_sections} sections)")
    print(f"   💰 Total cost: ${total_cost:.4f} (search: ${search_cost:.4f}, parse: ${parsing_cost:.4f}, refine: ${refinement_cost:.4f})")

    logger.info(
        "ToC parsed successfully (with refinement)",
        entries=len(toc.entries),
        chapters=toc.total_chapters,
        sections=toc.total_sections,
        confidence=f"{toc.parsing_confidence:.2f}",
        search_cost=f"${search_cost:.4f}",
        parsing_cost=f"${parsing_cost:.4f}",
        refinement_cost=f"${refinement_cost:.4f}",
        total_cost=f"${total_cost:.4f}",
    )

    return toc, total_cost
