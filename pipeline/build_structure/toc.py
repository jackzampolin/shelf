"""
Table of Contents extraction from merged pages.

Extracts the book's declared structure from ToC pages using a two-pass approach:
1. Initial parse: Text + images for hierarchy detection
2. Refinement: Images + error guidance to fix common issues

Cost: ~$0.10-0.15 per book (search + initial parse + refinement)
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
from .toc_prompts import TOC_STRUCTURE_DETECTION_PROMPT, build_detail_extraction_prompt


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


def detect_toc_structure(
    toc_images: list,
    model: str,
    logger: PipelineLogger,
    log_dir: Path,
) -> Tuple[dict, float]:
    """
    STAGE 1: Detect document-level ToC structure.

    Args:
        toc_images: List of ToC page images
        model: LLM model to use
        logger: Pipeline logger
        log_dir: Directory for logging

    Returns:
        Tuple of (structure_overview dict, detection cost)
    """
    logger.info("Stage 1: Detecting ToC structure (document-level)", toc_pages=len(toc_images))
    print(f"   🔍 Stage 1: Analyzing document structure...")

    # Simple schema for structure detection output
    structure_schema = {
        "type": "object",
        "properties": {
            "structure_overview": {
                "type": "object",
                "properties": {
                    "total_entries_visible": {"type": "integer"},
                    "total_chapters": {"type": "integer"},
                    "total_sections": {"type": "integer"},
                    "numbering_pattern": {"type": "string"},
                    "expected_range": {"type": "string"},
                    "hierarchy_levels": {"type": "integer"},
                    "has_parts": {"type": "boolean"},
                    "formatting_pattern": {"type": "string"},
                    "detected_gaps": {"type": "array", "items": {"type": "integer"}},
                    "visual_observations": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["total_entries_visible", "total_chapters", "numbering_pattern", "expected_range", "hierarchy_levels"]
            },
            "confidence": {"type": "number"},
            "notes": {"type": "array", "items": {"type": "string"}}
        },
        "required": ["structure_overview", "confidence"]
    }

    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "toc_structure_detection",
            "schema": structure_schema
        }
    }

    # Create structure detection request (vision-only, no text)
    request = LLMRequest(
        id="detect_structure",
        model=model,
        messages=[
            {"role": "system", "content": TOC_STRUCTURE_DETECTION_PROMPT},
            {"role": "user", "content": "Analyze these ToC pages and identify the overall document structure."}
        ],
        images=toc_images,
        temperature=0.0,
        max_tokens=2000,
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
        raise ValueError(f"Structure detection failed: {result.error_message}")

    structure_data = result.parsed_json
    structure_overview = structure_data["structure_overview"]
    detection_cost = result.cost_usd

    # Log structure findings
    logger.info(
        "Structure detected",
        total_entries=structure_overview["total_entries_visible"],
        chapters=structure_overview["total_chapters"],
        pattern=structure_overview["numbering_pattern"],
        range=structure_overview["expected_range"],
        levels=structure_overview["hierarchy_levels"],
        gaps=structure_overview.get("detected_gaps", []),
        cost=f"${detection_cost:.4f}"
    )

    print(f"   ✓ Structure: {structure_overview['total_entries_visible']} entries, "
          f"{structure_overview['total_chapters']} chapters, "
          f"pattern={structure_overview['numbering_pattern']}, "
          f"levels={structure_overview['hierarchy_levels']}")

    if structure_overview.get("detected_gaps"):
        print(f"   ⚠️  Detected gaps in numbering: {structure_overview['detected_gaps']}")

    return structure_overview, detection_cost


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

    # Load ToC images for vision-based parsing
    toc_images = load_toc_images(storage, toc_range)
    log_dir = storage.stage("build_structure").output_dir / "logs"

    # STAGE 1: Detect document-level structure
    structure_overview, structure_cost = detect_toc_structure(
        toc_images=toc_images,
        model=model,
        logger=logger,
        log_dir=log_dir
    )

    # STAGE 2: Extract details using structure context
    logger.info("Stage 2: Extracting ToC entries (structure-guided)", model=model)
    print(f"   📝 Stage 2: Extracting entries with structure guidance...")

    # Build Stage 2 prompt with structure context
    detail_prompt = build_detail_extraction_prompt(structure_overview)

    # Build JSON schema for structured output
    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "table_of_contents",
            "schema": TableOfContents.model_json_schema()
        }
    }

    # Create detail extraction request
    request = LLMRequest(
        id="extract_details",
        model=model,
        messages=[
            {"role": "system", "content": detail_prompt},
            {"role": "user", "content": f"Extract ALL entries from the ToC following the structure guidance above.\n\nToC page range (scan pages): {toc_range.start_page}-{toc_range.end_page}"}
        ],
        images=toc_images,  # Same images, now with structure context
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
        raise ValueError(f"Detail extraction failed: {result.error_message}")

    # Parse response as TableOfContents
    toc = TableOfContents(**result.parsed_json)
    extraction_cost = result.cost_usd

    total_cost = search_cost + structure_cost + extraction_cost

    print(f"   ✓ Extracted: {len(toc.entries)} entries ({toc.total_chapters} chapters, {toc.total_sections} sections)")
    print(f"   💰 Total cost: ${total_cost:.4f} (search: ${search_cost:.4f}, structure: ${structure_cost:.4f}, extract: ${extraction_cost:.4f})")

    logger.info(
        "ToC parsed successfully (two-stage holistic)",
        entries=len(toc.entries),
        chapters=toc.total_chapters,
        sections=toc.total_sections,
        confidence=f"{toc.parsing_confidence:.2f}",
        search_cost=f"${search_cost:.4f}",
        structure_cost=f"${structure_cost:.4f}",
        extraction_cost=f"${extraction_cost:.4f}",
        total_cost=f"${total_cost:.4f}",
    )

    return toc, total_cost
