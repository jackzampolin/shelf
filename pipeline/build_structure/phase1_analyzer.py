"""
Phase 1: Analyze report.csv to extract draft structure metadata.

This phase reads the labels/report.csv file and uses an LLM to identify:
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

from infra.llm.client import LLMClient
from infra.pipeline.logger import PipelineLogger

from .schemas import DraftMetadata, TableOfContents, HeadingData
from .prompts_v2 import STRUCTURE_ANALYSIS_SYSTEM_PROMPT, build_user_prompt


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

    # Prepare structured output request (same format as label/correction stages)
    response_schema = DraftMetadata.model_json_schema()

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

    # Make LLM call with structured output and streaming for progress
    client = LLMClient()
    logger.info("Calling LLM for structure analysis", model=model, pages=total_pages)
    print(f"\n📊 Analyzing book structure ({total_pages} pages)...")

    response_text, usage, cost_usd = client.call(
        model=model,
        messages=messages,
        response_format=response_schema,  # Pass Pydantic schema directly
        max_tokens=4000,  # Structure metadata should be concise
        stream=True,  # Enable streaming for progress feedback
    )

    logger.info(
        "LLM response received",
        tokens_in=usage.get("prompt_tokens", 0),
        tokens_out=usage.get("completion_tokens", 0),
        cost=f"${cost_usd:.4f}",
    )

    # Parse response into DraftMetadata
    import json

    if not response_text or not response_text.strip():
        logger.error("Empty LLM response!")
        raise ValueError("LLM returned empty response")

    logger.info("Response length", chars=len(response_text))

    # Strip markdown code fences if present
    response_text = response_text.strip()
    if response_text.startswith("```json"):
        response_text = response_text[7:]  # Remove ```json
    if response_text.startswith("```"):
        response_text = response_text[3:]  # Remove ```
    if response_text.endswith("```"):
        response_text = response_text[:-3]  # Remove trailing ```
    response_text = response_text.strip()

    # Extract just the JSON object (handle extra text after JSON closes)
    # Find the first { and the last matching }
    first_brace = response_text.find('{')
    if first_brace == -1:
        logger.error("No JSON object found in response", response_preview=response_text[:500])
        raise ValueError("LLM response doesn't contain JSON object")

    # Find matching closing brace by counting braces
    brace_count = 0
    last_brace = first_brace
    for i in range(first_brace, len(response_text)):
        if response_text[i] == '{':
            brace_count += 1
        elif response_text[i] == '}':
            brace_count -= 1
            if brace_count == 0:
                last_brace = i
                break

    # Extract just the JSON object
    json_text = response_text[first_brace:last_brace+1]

    try:
        response_data = json.loads(json_text)
        draft = DraftMetadata(**response_data)
    except json.JSONDecodeError as e:
        logger.error("Invalid JSON from LLM", error=str(e), response_preview=response_text[:1000])
        raise ValueError(f"LLM response is not valid JSON: {e}")
    except Exception as e:
        logger.error("Failed to validate schema", error=str(e), response_type=type(response_data).__name__)
        raise ValueError(f"LLM response doesn't match DraftMetadata schema: {e}")

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
