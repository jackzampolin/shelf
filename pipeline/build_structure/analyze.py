"""
Structure analysis from labels report.

Analyzes labels/report.csv and optional ToC/headings to extract book structure:
- Front matter (title, copyright, TOC, preface, etc.)
- Chapters and sections
- Back matter (epilogue, notes, bibliography, index, etc.)
- Page numbering patterns

Cost: ~$0.10-0.20 per book (single LLM call on ~50KB CSV)
Time: ~10-30 seconds
"""

import csv
from pathlib import Path
from typing import Tuple, Optional

from infra.llm.batch_client import LLMBatchClient
from infra.llm.models import LLMRequest
from infra.pipeline.logger import PipelineLogger

from .schemas import DraftMetadata, TableOfContents, HeadingData
from .analyze_prompts import STRUCTURE_ANALYSIS_SYSTEM_PROMPT, build_user_prompt


def format_report_for_llm(rows: list[dict]) -> str:
    """
    Format report.csv data as a readable TSV table for LLM.

    Args:
        rows: List of dicts from csv.DictReader

    Returns:
        TSV-formatted string with header and data rows
    """
    if not rows:
        return ""

    # Define column order (subset of available columns)
    columns = [
        "page_num",
        "printed_page_number",
        "numbering_style",
        "page_region",
        "total_blocks_classified",
        "avg_classification_confidence",
        "has_chapter_heading",
        "has_section_heading",
    ]

    # Build header
    lines = ["\t".join(columns)]

    # Build data rows
    for row in rows:
        values = []
        for col in columns:
            val = row.get(col, "")
            # Handle None/null values
            if val is None or val == "":
                val = "null"
            values.append(str(val))
        lines.append("\t".join(values))

    return "\n".join(lines)


def analyze_report(
    labels_report_path: Path,
    toc: Optional[TableOfContents],
    heading_data: Optional[HeadingData],
    model: str,
    logger: PipelineLogger,
) -> Tuple[DraftMetadata, float]:
    """
    Analyze labels/report.csv to extract book structure.

    Phase 1b of build-structure: Analyze report informed by ToC and heading data.

    Args:
        labels_report_path: Path to labels/report.csv
        toc: Parsed Table of Contents (from Phase 1a) or None
        heading_data: Extracted heading text (from Phase 1.5) or None
        model: LLM model to use (e.g., "anthropic/claude-sonnet-4.5")
        logger: Pipeline logger

    Returns:
        Tuple of (DraftMetadata, cost_usd)

    Raises:
        FileNotFoundError: If report.csv doesn't exist
        ValueError: If LLM response doesn't match schema
    """
    logger.info(
        "Phase 1b: Analyzing report.csv",
        path=str(labels_report_path),
        has_toc=toc is not None,
        has_headings=heading_data is not None,
    )

    # Load report.csv
    if not labels_report_path.exists():
        raise FileNotFoundError(f"Labels report not found: {labels_report_path}")

    with open(labels_report_path, "r") as f:
        rows = list(csv.DictReader(f))

    total_pages = len(rows)
    logger.info("Loaded report", pages=total_pages, size_kb=labels_report_path.stat().st_size // 1024)

    # Format for LLM
    report_text = format_report_for_llm(rows)

    # Format ToC as JSON string if available
    toc_json = None
    if toc:
        import json
        toc_json = json.dumps(toc.model_dump(), indent=2)
        logger.info(
            "Including ToC in analysis",
            toc_chapters=toc.total_chapters,
            toc_sections=toc.total_sections,
            toc_confidence=f"{toc.parsing_confidence:.2f}",
        )

    # Format heading data as JSON string if available
    headings_json = None
    if heading_data:
        import json
        headings_json = json.dumps(heading_data.model_dump(), indent=2)
        logger.info(
            "Including heading data in analysis",
            total_headings=heading_data.total_headings,
            parts=heading_data.part_count,
            chapters=heading_data.chapter_count,
        )

    # Build prompts using new V2 structure
    user_prompt = build_user_prompt(
        report_csv=report_text,
        toc_json=toc_json,
        headings_json=headings_json,
    )

    messages = [
        {"role": "system", "content": STRUCTURE_ANALYSIS_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    # Build JSON schema for structured output
    # Note: OpenRouter doesn't support "strict": True
    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "draft_metadata",
            "schema": DraftMetadata.model_json_schema()
        }
    }

    # Create LLM request
    request = LLMRequest(
        id="analyze_structure",
        model=model,
        messages=messages,
        temperature=0.0,
        max_tokens=4000,  # Structure metadata should be concise
        response_format=response_format
    )

    # Make LLM call with batch client (single request)
    log_dir = labels_report_path.parent.parent / "build_structure" / "logs"
    batch_client = LLMBatchClient(
        max_workers=1,
        max_retries=5,  # Retry on validation failures
        verbose=False,  # Disable verbose for single call (we'll show our own progress)
        log_dir=log_dir
    )

    logger.info("Calling LLM for structure analysis", model=model, pages=total_pages)
    print(f"\n📊 Analyzing book structure ({total_pages} pages)...")
    print(f"   ⏳ Calling LLM...")

    results = batch_client.process_batch([request])

    # Show completion with cost
    batch_stats = batch_client.get_batch_stats(total_requests=1)
    print(f"   ✓ Complete (cost: ${batch_stats.total_cost_usd:.4f})")

    # Extract result
    result = results[0]
    if not result.success:
        raise ValueError(f"LLM call failed: {result.error_message}")

    # Parse response as DraftMetadata
    draft = DraftMetadata(**result.parsed_json)
    cost_usd = result.cost_usd

    logger.info(
        "LLM response validated",
        cost=f"${cost_usd:.4f}",
    )

    logger.info(
        "Draft structure extracted",
        chapters=draft.total_chapters,
        sections=draft.total_sections,
        front_matter_pages=draft.front_matter.toc.end_page - draft.front_matter.toc.start_page + 1
        if draft.front_matter.toc
        else 0,
        body_pages=len(draft.body_page_range),
    )

    return draft, cost_usd
